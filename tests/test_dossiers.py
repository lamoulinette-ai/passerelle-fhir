"""Ce que la sonde des dossiers cherche, et ce qu'elle ne fait jamais.

Trois propriétés priment :

- **aucune requête modifiante** — elle interroge des bacs à sable partagés, et une écriture
  accidentelle y abîmerait le travail d'autrui sans que rien dans sa sortie le signale ;
- **un candidat est relu par `apparier`**, qui applique le périmètre déclaré : la recherche
  par code l'ignore, et retenir sur elle seule promettrait des pathologies absentes ;
- **une condition résolue ne fait pas un porteur** — seuls les statuts actifs comptent.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from passerelle.fhir.client import ClientFhir
from passerelle.sondes.dossiers import en_markdown, examiner

Gestionnaire = Callable[[httpx.Request], httpx.Response]
BASE = "https://exemple.test/fhir"
PATIENT = "patient-essai"


def _client(gestionnaire: Gestionnaire) -> ClientFhir:
    transport = httpx.MockTransport(gestionnaire)
    return ClientFhir(adresse=BASE, client=httpx.Client(transport=transport))


def _condition(code: str, statut: str = "active") -> dict:
    return {
        "resourceType": "Condition",
        "clinicalStatus": {"coding": [{"code": statut}]},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": code}]},
    }


def _serveur(conditions: list[dict], journal: list[httpx.Request] | None = None) -> Gestionnaire:
    """Un serveur d'essai rendant un patient vivant et les conditions données."""

    def repondre(requete: httpx.Request) -> httpx.Response:
        if journal is not None:
            journal.append(requete)
        if "/Patient/" in requete.url.path:
            return httpx.Response(
                200,
                json={
                    "resourceType": "Patient",
                    "id": PATIENT,
                    "gender": "female",
                    "birthDate": "1960-01-01",
                },
            )
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [{"resource": c} for c in conditions],
            },
        )

    return repondre


class TestInnocuite:
    def test_aucune_requete_modifiante(self) -> None:
        vues: list[httpx.Request] = []
        client = _client(_serveur([_condition("44054006")], vues))
        examiner(client, [PATIENT])
        assert vues, "la sonde n'a rien émis, le test ne prouverait rien"
        assert all(requete.method == "GET" for requete in vues)


class TestRelecture:
    def test_un_dossier_est_relu_par_le_chemin_vif(self) -> None:
        """Deux codes de deux pathologies : la relecture doit rendre les deux."""
        conditions = [_condition("44054006"), _condition("88805009")]
        dossiers = examiner(_client(_serveur(conditions)), [PATIENT])
        assert dossiers[0]["pathologies"] == ["diabete", "insuffisance_cardiaque"]

    def test_une_condition_resolue_ne_compte_pas(self) -> None:
        """Le chemin vif ignore les problèmes résolus ; la sonde doit dire pareil."""
        conditions = [_condition("44054006"), _condition("88805009", "resolved")]
        dossiers = examiner(_client(_serveur(conditions)), [PATIENT])
        assert dossiers[0]["pathologies"] == ["diabete"]

    def test_les_conditions_lues_sont_comptees_toutes(self) -> None:
        """Le décompte porte sur ce qui a été lu, pas sur ce qui a été retenu."""
        conditions = [_condition("44054006"), _condition("444814009")]
        dossiers = examiner(_client(_serveur(conditions)), [PATIENT])
        assert dossiers[0]["conditions"] == 2
        assert dossiers[0]["pathologies"] == ["diabete"]

    def test_un_patient_vivant_est_reconnu(self) -> None:
        dossiers = examiner(_client(_serveur([_condition("44054006")])), [PATIENT])
        assert dossiers[0]["vivant"] is True
        assert dossiers[0]["age"] is not None

    def test_un_dossier_injoignable_est_ignore_sans_lever(self) -> None:
        """Un candidat illisible ne doit pas emporter le relevé des autres."""

        def tomber(_requete: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("injoignable")

        assert examiner(_client(tomber), [PATIENT]) == []


class TestRendu:
    def test_l_absence_de_candidat_est_dite(self) -> None:
        rendu = en_markdown([], minimum=2)
        assert "aucun candidat" in rendu

    def test_un_patient_mort_est_signale(self) -> None:
        """Le premier patient retenu au bloc 1 était mort en 1969 : ça doit se voir."""
        dossier = {
            "identifiant": "x",
            "sexe": "male",
            "age": 60,
            "vivant": False,
            "conditions": 3,
            "pathologies": ["diabete"],
            "deja_retenu": False,
        }
        assert "**non**" in en_markdown([dossier], minimum=1)
