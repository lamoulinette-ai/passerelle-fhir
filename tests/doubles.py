"""Les doubles des trois services extérieurs, et de quoi les régler.

Ils vivent ici plutôt que dans `conftest.py` pour être importables par leur nom : un test qui
change le dossier rendu écrit `FauxFhir([...])`, et le lire dans le corps du test vaut mieux
que de le deviner derrière une fixture.

**La suite ne touche pas au réseau.** Chacun de ces doubles remplace un appel qui, sans lui,
partirait vers un bac à sable public, le serveur de l'ANS ou le moteur documentaire.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from passerelle.documentaliste.client import Documentaliste
from passerelle.fhir.client import FhirIndisponible
from passerelle.terminologie.client import TerminologieIndisponible
from passerelle.terminologie.schemas import Concept

EXEMPLES = Path(__file__).parent / "exemples" / "reponses"

DANS_LA_DEMO = "bd6f9f37-7295-4cd6-b212-134afcef1253"
AUTRE = "8364ff74-d904-442b-b984-f9d640531639"

PATIENT = {
    "resourceType": "Patient",
    "id": DANS_LA_DEMO,
    "gender": "male",
    "birthDate": "1956-03-10",
}


def condition(code: str, statut: str = "active") -> dict:
    return {
        "resourceType": "Condition",
        "clinicalStatus": {"coding": [{"code": statut}]},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": code}]},
    }


class FauxFhir:
    """Un serveur FHIR d'essai, dont on choisit le dossier rendu."""

    def __init__(self, conditions: list[dict] | None = None, tombe: bool = False) -> None:
        self.conditions_rendues = conditions if conditions is not None else []
        self.tombe = tombe

    def patient(self, _identifiant: str) -> dict:
        if self.tombe:
            raise FhirIndisponible("injoignable")
        return PATIENT

    def conditions(self, _identifiant: str) -> list[dict]:
        if self.tombe:
            raise FhirIndisponible("injoignable")
        return self.conditions_rendues

    def fermer(self) -> None:
        return None


class FausseTerminologie:
    """Un serveur de terminologies d'essai, dont on choisit ce qu'il résout."""

    def __init__(self, libelles: dict[str, str] | None = None, tombe: bool = False) -> None:
        self.libelles = libelles if libelles is not None else {"44054006": "diabète de type 2"}
        self.tombe = tombe

    def resoudre(self, systeme: str, code: str) -> Concept:
        if self.tombe:
            raise TerminologieIndisponible("injoignable")
        return Concept(
            systeme=systeme,
            code=code,
            display=self.libelles.get(code, ""),
            libelle_fr=self.libelles.get(code),
            version="version-d-essai",
            terminologie="module d'essai",
        )

    def fermer(self) -> None:
        return None


def faux_documentaliste(gestionnaire) -> Documentaliste:  # noqa: ANN001
    return Documentaliste(
        adresse="https://exemple.test",
        client=httpx.Client(transport=httpx.MockTransport(gestionnaire)),
        exemples=EXEMPLES,
    )


REPONSE = {
    "question": "q",
    "issue": "reponse",
    "affirmations": [{"texte": "Une phrase.", "extrait": 1}],
    "passages": [{"numero": 1, "document": "has_1", "page": 1, "texte": "t", "titre": "Guide"}],
    "defauts": [],
    "redaction_indisponible": False,
}


def interroger(client: TestClient, brancher: dict, code: str) -> httpx.Response:
    """Consulte un dossier portant ce seul code, puis désigne ce code — comme le ferait la page."""
    brancher["fhir"] = FauxFhir([condition(code)])
    trace = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
    return client.post("/interroger", json={"trace": trace, "code": code})
