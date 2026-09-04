"""Appel au moteur documentaire, et repli sur les réponses enregistrées.

L'appel se fait **de serveur à serveur**. La page n'interroge jamais l'API du documentaliste
directement : elle y récupérerait un refus d'origine croisée, et surtout ses appels
n'apparaîtraient dans aucune trace.

Le client ne lève pas. Panne, délai dépassé, plafond de rédaction atteint : il sert la
réponse enregistrée du gabarit et nomme la cause. Une démonstration qui dégrade vaut mieux
qu'une démonstration qui meurt.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

from passerelle.documentaliste.schemas import Reponse

journal = logging.getLogger("passerelle.documentaliste")

API_DEFAUT = "https://documentaliste.lamoulinette.ai"

#: Réponses enregistrées, une par gabarit. Extraites du corpus de la HAS, diffusé sous
#: Licence Ouverte 2.0 : leur présence dans le dépôt est permise, et sans elles le mode
#: dégradé n'existerait que sur le papier.
#:
#: Elles vivent dans le paquet et non à la racine : le repli doit fonctionner une fois
#: l'application installée, où la racine du dépôt n'existe plus.
ENREGISTREES = Path(__file__).parent / "exemples"


def api() -> str:
    """Adresse de l'API documentaire, lue dans l'environnement."""
    return os.environ.get("PASSERELLE_DOCUMENTALISTE_API", "").strip() or API_DEFAUT


def delai() -> float:
    """Délai maximal d'une interrogation, en secondes."""
    brut = os.environ.get("PASSERELLE_DOCUMENTALISTE_DELAI", "").strip()
    try:
        return float(brut) if brut else 30.0
    except ValueError:
        journal.warning("PASSERELLE_DOCUMENTALISTE_DELAI illisible (%r) — repli sur 30 s", brut)
        return 30.0


def enregistree(gabarit: str, dossier: Path | None = None) -> Reponse | None:
    """Rend la réponse enregistrée d'un gabarit, ou `None` s'il n'en existe pas."""
    fichier = (dossier or ENREGISTREES) / f"{gabarit}.json"
    if not fichier.is_file():
        return None
    try:
        charge = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        journal.warning("réponse enregistrée illisible : %s", fichier.name)
        return None
    charge["origine"] = "enregistrée"
    return Reponse.model_validate(charge)


class Documentaliste:
    """Client du moteur documentaire, avec repli."""

    def __init__(
        self,
        adresse: str | None = None,
        client: httpx.Client | None = None,
        exemples: Path | None = None,
    ) -> None:
        self.adresse = (adresse or api()).rstrip("/")
        self.exemples = exemples
        self._client = client or httpx.Client(timeout=delai())
        journal.info("moteur documentaire : %s", self.adresse)

    def interroger(self, question: str, gabarit: str = "") -> tuple[Reponse | None, str]:
        """Pose une question et rend `(réponse, cause de dégradation)`.

        La cause est vide quand le service a répondu. Elle est renseignée dès qu'un repli a
        lieu, y compris quand ce repli réussit : c'est elle que le journal consigne.
        """
        try:
            reponse = self._client.post(f"{self.adresse}/question", json={"question": question})
            reponse.raise_for_status()
            rendue = Reponse.model_validate(reponse.json())
        except httpx.HTTPStatusError as erreur:
            return self._replier(gabarit, f"service en erreur ({erreur.response.status_code})")
        except httpx.HTTPError as erreur:
            return self._replier(gabarit, f"service injoignable ({type(erreur).__name__})")
        except ValueError:
            return self._replier(gabarit, "réponse du service illisible")

        if rendue.redaction_indisponible:
            journal.info("rédaction indisponible en amont — passages conservés")
        return rendue, ""

    def _replier(self, gabarit: str, cause: str) -> tuple[Reponse | None, str]:
        """Sert la réponse enregistrée du gabarit, en conservant la cause du repli."""
        if not gabarit:
            journal.warning("aucun repli demandé — %s", cause)
            return None, cause
        journal.warning("repli sur réponse enregistrée — %s", cause)
        secours = enregistree(gabarit, self.exemples)
        if secours is None:
            return None, f"{cause}, et aucune réponse enregistrée pour « {gabarit} »"
        return secours, cause

    def fermer(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        self._client.close()
