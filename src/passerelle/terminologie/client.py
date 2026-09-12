"""Résolution terminologique contre le Serveur Multi-Terminologies de l'ANS.

`$lookup` répond **sans authentification** — mesuré depuis deux machines et deux réseaux. Le
client n'envoie donc aucune identification.

**Quand une clé deviendrait nécessaire**, et ce qu'il faudrait alors écrire : le SMT protège
le téléchargement des référentiels entiers, et fermerait `$lookup` s'il changeait de
politique. La clé d'API du SMT **n'est pas un jeton porteur** : elle s'échange contre un JWT,
et c'est ce JWT qui va dans `Authorization: Bearer`. L'envoyer telle quelle rend 401 — mesuré
en production, sur un chemin qui n'avait jamais été exécuté nulle part. Implémenter l'échange,
sa péremption et son renouvellement est le travail à faire ce jour-là, pas avant.

Ce que la clé atteste, en revanche, ne se lit dans aucune réponse HTTP : l'affiliation au
centre national français est ce qui rend l'usage licite, avec ou sans elle, et les mentions de
licence du README en découlent.
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict

import httpx

from passerelle.terminologie.schemas import Concept

journal = logging.getLogger("passerelle.terminologie")

BASE_DEFAUT = "https://smt.esante.gouv.fr/fhir"

#: Concepts conservés en mémoire. Le conteneur est en lecture seule, et un concept ne change
#: qu'entre deux versions du référentiel.
MEMOIRE = 512

#: Langue demandée explicitement. Le serveur français répond déjà en français, mais un
#: paramètre déclaré vaut mieux qu'un comportement supposé.
LANGUE = "fr"


class TerminologieIndisponible(RuntimeError):
    """Le serveur de terminologies n'a pas répondu, ou a répondu autre chose qu'un concept."""


class ConceptInconnu(TerminologieIndisponible):
    """Le serveur a répondu, et ne connaît ni ce code ni ce système.

    Distincte d'une panne, et la distinction n'est pas cosmétique : le serveur français
    n'héberge pas tous les référentiels du monde, et un dossier venu d'ailleurs en porte.
    Appeler cela une indisponibilité ferait passer une réponse juste pour un incident.

    Sous-classe plutôt qu'exception indépendante : un appelant qui ne fait pas la différence
    — les sondes, par exemple — continue de fonctionner sans rien savoir de ce cas.
    """


def base() -> str:
    """Base du serveur de terminologies, lue dans l'environnement."""
    return os.environ.get("PASSERELLE_SMT_BASE", "").strip() or BASE_DEFAUT


#: Usages qui désignent le terme retenu pour une langue, par opposition aux synonymes.
#:
#: Le serveur écrit le même usage de deux façons — `preferredForLanguage` sur une ligne,
#: `Preferred For Language` sur une autre. C'est le **code** de la codification qui est
#: comparé, normalisé : se fier à son affichage ferait manquer une ligne sur deux.
PREFERES = frozenset({"preferredforlanguage"})


def _est_francaise(langue: str) -> bool:
    """Vrai pour `fr` comme pour les variantes régionales `fr-x-sctlang-…`."""
    return langue == LANGUE or langue.startswith(f"{LANGUE}-")


def _designation_francaise(charge: dict) -> str | None:
    """Rend la désignation française retenue pour la langue, ou `None` s'il n'y en a aucune.

    Un concept porte plusieurs désignations françaises : le terme préféré, et des synonymes.
    Prendre la première venue donne un synonyme au hasard — mesuré sur `271737000`, qui rend
    « anemia » avant « anémie ». L'usage est donc lu, et le terme préféré l'emporte.

    L'existence d'une désignation française reste le seul critère qui distingue une
    traduction d'un repli : le serveur rend un `display` dans tous les cas, y compris pour un
    concept jamais traduit.
    """
    preferee, premiere = None, None
    for parametre in charge.get("parameter", []):
        if parametre.get("name") != "designation":
            continue
        parts = {p.get("name"): p for p in parametre.get("part", [])}
        if not _est_francaise(str(parts.get("language", {}).get("valueCode", ""))):
            continue
        valeur = parts.get("value", {}).get("valueString")
        if not valeur:
            continue
        premiere = premiere or str(valeur)
        usage = str((parts.get("use", {}).get("valueCoding") or {}).get("code", ""))
        if usage.replace(" ", "").lower() in PREFERES:
            preferee = preferee or str(valeur)
    return preferee or premiere


def _simple(charge: dict, nom: str) -> str:
    """Lit un paramètre de premier niveau rendu comme chaîne."""
    for parametre in charge.get("parameter", []):
        if parametre.get("name") == nom:
            for cle_valeur in ("valueString", "valueCode", "valueUri"):
                if cle_valeur in parametre:
                    return str(parametre[cle_valeur])
    return ""


class Terminologie:
    """Client `$lookup`, avec cache borné."""

    def __init__(self, adresse: str | None = None, client: httpx.Client | None = None) -> None:
        self.adresse = (adresse or base()).rstrip("/")
        entetes = {"Accept": "application/fhir+json"}
        self._client = client or httpx.Client(timeout=10.0, headers=entetes)
        self._cache: OrderedDict[tuple[str, str], Concept] = OrderedDict()

    def resoudre(self, systeme: str, code: str) -> Concept:
        """Rend le concept, depuis le cache s'il y est déjà."""
        empreinte = (systeme, code)
        if empreinte in self._cache:
            self._cache.move_to_end(empreinte)
            return self._cache[empreinte]

        concept = self._interroger(systeme, code)
        self._cache[empreinte] = concept
        while len(self._cache) > MEMOIRE:
            self._cache.popitem(last=False)
        return concept

    def _interroger(self, systeme: str, code: str) -> Concept:
        """Interroge `$lookup` et assemble un `Concept`."""
        parametres = {"system": systeme, "code": code, "displayLanguage": LANGUE}
        try:
            reponse = self._client.get(f"{self.adresse}/CodeSystem/$lookup", params=parametres)
            reponse.raise_for_status()
            charge = reponse.json()
        except httpx.HTTPStatusError as erreur:
            # Une adresse de base erronée rendrait 404 elle aussi. Ce cas-là est couvert
            # ailleurs : le concept témoin est éprouvé au démarrage du service, et son échec
            # est une indisponibilité déclarée avant la première consultation.
            if erreur.response.status_code == httpx.codes.NOT_FOUND:
                raise ConceptInconnu(f"{systeme}|{code}") from erreur
            raise TerminologieIndisponible(f"{systeme}|{code} : {erreur}") from erreur
        except httpx.HTTPError as erreur:
            raise TerminologieIndisponible(f"{systeme}|{code} : {erreur}") from erreur
        except ValueError as erreur:
            raise TerminologieIndisponible(f"{systeme}|{code} : réponse illisible") from erreur

        if charge.get("resourceType") != "Parameters":
            raise TerminologieIndisponible(f"{systeme}|{code} : réponse inattendue")

        return Concept(
            systeme=systeme,
            code=code,
            display=_simple(charge, "display"),
            libelle_fr=_designation_francaise(charge),
            version=_simple(charge, "version"),
            terminologie=_simple(charge, "name"),
        )

    def charge(self, systeme: str, code: str) -> dict:
        """Rend la réponse `$lookup` telle quelle, sans en retenir un seul champ.

        Employée par la sonde pour montrer **toutes** les désignations d'un concept, avec
        leur langue et leur usage. `resoudre` en choisit une ; c'est ce choix qu'il faut
        pouvoir contrôler.
        """
        parametres = {"system": systeme, "code": code, "displayLanguage": LANGUE}
        try:
            reponse = self._client.get(f"{self.adresse}/CodeSystem/$lookup", params=parametres)
            reponse.raise_for_status()
            return dict(reponse.json())
        except (httpx.HTTPError, ValueError) as erreur:
            raise TerminologieIndisponible(f"{systeme}|{code} : {erreur}") from erreur

    def fermer(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        self._client.close()
