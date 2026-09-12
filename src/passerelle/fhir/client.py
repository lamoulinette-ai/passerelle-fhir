"""Transport HTTP vers un serveur FHIR R4, en lecture seule."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

journal = logging.getLogger("passerelle.fhir")

#: Point d'entrée R4 du SMART App Launcher, employé faute de `PASSERELLE_FHIR_BASE`.
#:
#: Le segment `sim/e30` porte des options de lancement vides mais valides. Sans lui, la
#: lecture fonctionne mais le point d'autorisation refuse toute demande : il tente de
#: décoder une chaîne vide. Mesuré.
BASE_DEFAUT = "https://launch.smarthealthit.org/v/r4/sim/e30/fhir"

#: Nombre maximal de ressources demandées par page de recherche.
PAGE = 100


class FhirIndisponible(RuntimeError):
    """Le serveur FHIR n'a pas répondu, ou a répondu autre chose qu'une ressource."""


def base() -> str:
    """Base du serveur FHIR, lue dans l'environnement."""
    return os.environ.get("PASSERELLE_FHIR_BASE", "").strip() or BASE_DEFAUT


def delai() -> float:
    """Délai maximal d'une requête, en secondes."""
    brut = os.environ.get("PASSERELLE_FHIR_DELAI", "").strip()
    try:
        return float(brut) if brut else 10.0
    except ValueError:
        journal.warning("PASSERELLE_FHIR_DELAI illisible (%r) — repli sur 10 s", brut)
        return 10.0


class ClientFhir:
    """Client de lecture. N'écrit jamais : aucune méthode ne produit de requête modifiante."""

    def __init__(
        self,
        adresse: str | None = None,
        client: httpx.Client | None = None,
        entetes: dict[str, str] | None = None,
    ) -> None:
        """Construit le transport. `entetes` porte l'autorisation, quand il y en a une.

        `Accept` est posé **en dernier** : un serveur au moins rend 406 sans lui, et aucun
        appelant n'a de raison légitime de le remplacer.
        """
        self.adresse = (adresse or base()).rstrip("/")
        self._client = client or httpx.Client(
            timeout=delai(),
            headers={**(entetes or {}), "Accept": "application/fhir+json"},
        )
        journal.info("serveur FHIR : %s", self.adresse)

    def patient(self, identifiant: str) -> dict[str, Any]:
        """Lit une ressource `Patient` par son identifiant."""
        return self._lire(f"/Patient/{identifiant}")

    def conditions(self, identifiant: str) -> list[dict[str, Any]]:
        """Lit les `Condition` d'un patient, toutes pages confondues."""
        return self._rechercher("/Condition", {"patient": identifiant})

    def rechercher_conditions(self, parametres: dict[str, str]) -> list[dict[str, Any]]:
        """Recherche des `Condition` sur des critères libres, toutes pages confondues.

        Employée pour retrouver les porteurs d'un code sans balayer tous les dossiers.
        Lecture seule, comme le reste du client : aucune méthode d'écriture n'existe ici.
        """
        return self._rechercher("/Condition", parametres)

    def _rechercher(self, chemin: str, parametres: dict[str, str]) -> list[dict[str, Any]]:
        """Suit les liens `next` d'un `Bundle` de recherche et rend les ressources trouvées."""
        page = self._lire(chemin, {**parametres, "_count": str(PAGE)})
        ressources: list[dict[str, Any]] = []
        while True:
            ressources.extend(
                entree["resource"] for entree in page.get("entry") or [] if "resource" in entree
            )
            suivante = _suivante(page)
            if not suivante:
                return ressources
            page = self._lire_url(suivante)

    def _lire(self, chemin: str, parametres: dict[str, str] | None = None) -> dict[str, Any]:
        """Requête `GET` relative à la base."""
        return self._lire_url(f"{self.adresse}{chemin}", parametres)

    def _lire_url(self, url: str, parametres: dict[str, str] | None = None) -> dict[str, Any]:
        """Requête `GET` absolue, employée aussi pour suivre la pagination."""
        try:
            reponse = self._client.get(url, params=parametres)
            reponse.raise_for_status()
            charge = reponse.json()
        except httpx.HTTPError as erreur:
            raise FhirIndisponible(f"{url} : {erreur}") from erreur
        except ValueError as erreur:
            raise FhirIndisponible(f"{url} : réponse illisible") from erreur
        if not isinstance(charge, dict) or "resourceType" not in charge:
            raise FhirIndisponible(f"{url} : la réponse n'est pas une ressource FHIR")
        return charge

    def fermer(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        self._client.close()


def _suivante(page: dict[str, Any]) -> str | None:
    """Rend l'URL de la page suivante d'un `Bundle`, ou `None` s'il n'y en a pas."""
    for lien in page.get("link") or []:
        if lien.get("relation") == "next" and lien.get("url"):
            return str(lien["url"])
    return None
