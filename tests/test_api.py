"""Ce que le service rend, et ce qu'il refuse.

Quatre propriétés valent tous les autres tests de ce fichier :

- **une consultation dégradée rend un résultat et une trace qui nomme les causes** — sans
  quoi une clé absente et un service en panne seraient indiscernables d'un dossier vide ;
- **un patient hors contexte est refusé par la passerelle et le refus est consigné** — le
  serveur amont, lui, ne l'applique pas : c'est le seul contrôle qui ait lieu ;
- **un patient sans pathologie du périmètre produit zéro requête**, et c'est un résultat ;
- **`/health` distingue « je réponds » de « je réponds complètement »**.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from passerelle.api import service
from passerelle.api.schemas import Consultation
from passerelle.documentaliste.client import Documentaliste
from passerelle.fhir.client import FhirIndisponible
from passerelle.journal.schemas import Frontiere, Mode
from passerelle.smart.schemas import Jeton

EXEMPLES = Path(__file__).parent / "exemples" / "reponses"

DANS_LA_DEMO = "bd6f9f37-7295-4cd6-b212-134afcef1253"
AUTRE = "8364ff74-d904-442b-b984-f9d640531639"

PATIENT = {
    "resourceType": "Patient",
    "id": DANS_LA_DEMO,
    "gender": "male",
    "birthDate": "1956-03-10",
}


def _condition(code: str, statut: str = "active") -> dict:
    return {
        "resourceType": "Condition",
        "clinicalStatus": {"coding": [{"code": statut}]},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": code}]},
    }


class _FauxFhir:
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


def _faux_documentaliste(gestionnaire) -> Documentaliste:  # noqa: ANN001
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


@pytest.fixture
def brancher(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Remplace les deux dépendances extérieures par des doubles."""
    reglages: dict = {"fhir": _FauxFhir(), "statut": 200, "charge": REPONSE}

    def fhir(*_a: object, **_k: object) -> _FauxFhir:
        return reglages["fhir"]

    def documentaliste(*_a: object, **_k: object) -> Documentaliste:
        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(reglages["statut"], json=reglages["charge"])

        return _faux_documentaliste(repondre)

    monkeypatch.setattr(service, "ClientFhir", fhir)
    monkeypatch.setattr(service, "Documentaliste", documentaliste)
    monkeypatch.delenv("PASSERELLE_SMT_CLE", raising=False)
    monkeypatch.setenv("RATELIMIT_ENABLED", "false")
    yield reglages


@pytest.fixture
def client(brancher: dict) -> Iterator[TestClient]:
    from passerelle.api.app import app, registre

    assert brancher, "les dépendances extérieures doivent être remplacées avant le service"
    registre.vider()
    with TestClient(app) as essai:
        yield essai
    registre.vider()


class TestSante:
    def test_le_service_repond(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200

    def test_sans_cle_smt_il_repond_mais_pas_completement(self, client: TestClient) -> None:
        etat = client.get("/health").json()
        assert etat["debout"] is True
        assert etat["complet"] is False
        assert etat["terminologie"] == "indisponible"


class TestPerimetre:
    def test_les_patients_et_pathologies_sont_annonces(self, client: TestClient) -> None:
        charge = client.get("/perimetre").json()
        assert len(charge["patients"]) == 5
        assert len(charge["pathologies"]) == 3

    def test_l_avertissement_est_rendu_par_l_api(self, client: TestClient) -> None:
        """Il ne doit pas être écrit dans la page : on pourrait l'y oublier."""
        assert "dispositif médical" in client.get("/perimetre").json()["avertissement"]


class TestConsultation:
    def test_une_pathologie_du_perimetre_produit_une_requete(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert len(rendue["requetes"]) == 1
        assert rendue["requetes"][0]["gabarit"] == "diabete"
        assert rendue["trace"]

    def test_deux_pathologies_produisent_deux_requetes(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006"), _condition("185086009")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert {r["gabarit"] for r in rendue["requetes"]} == {"diabete", "bpco"}

    def test_aucune_pathologie_du_perimetre_produit_zero_requete(
        self, client: TestClient, brancher: dict
    ) -> None:
        """C'est un résultat, pas un échec : la trace existe, les problèmes sont rendus."""
        brancher["fhir"] = _FauxFhir([_condition("444814009")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["requetes"] == []
        assert len(rendue["problemes"]) == 1
        assert rendue["problemes"][0]["dans_le_perimetre"] is False
        assert rendue["trace"]

    def test_une_condition_resolue_ne_declenche_rien(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006", "resolved")])
        assert client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["requetes"] == []

    def test_l_age_est_calcule(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = _FauxFhir([])
        assert client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["age"] >= 68


class TestDegradation:
    def test_l_absence_de_cle_smt_est_nommee(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        causes = " ".join(d["cause"] for d in rendue["degradations"])
        assert "Multi-Terminologies" in causes
        assert rendue["problemes"][0]["libelle_fr"] is None

    def test_un_moteur_en_panne_degrade_sans_vider(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        brancher["statut"], brancher["charge"] = 503, {}
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["requetes"], "la requête construite doit rester visible"
        assert rendue["requetes"][0]["origine"] == "enregistrée"
        assert any("503" in d["cause"] for d in rendue["degradations"])

    def test_un_serveur_fhir_injoignable_rend_une_trace(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir(tombe=True)
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["trace"]
        assert rendue["problemes"] == []
        assert any("FHIR" in d["cause"] for d in rendue["degradations"])


class TestEspacement:
    def test_deux_interrogations_sont_espacees(
        self, client: TestClient, brancher: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le fournisseur du modèle plafonne à une requête par seconde, par espace de travail.

        Deux pathologies produiraient deux appels dans la même seconde, et le second serait
        refusé — ce qui s'est produit en ligne avant cette pause.
        """
        pauses: list[float] = []
        monkeypatch.setattr(service.time, "sleep", pauses.append)
        brancher["fhir"] = _FauxFhir([_condition("44054006"), _condition("185086009")])

        client.post("/consulter", json={"patient": DANS_LA_DEMO})
        assert len(pauses) == 1, "une pause entre deux appels, aucune avant le premier"
        assert pauses[0] >= 1.0

    def test_une_seule_interrogation_n_attend_pas(
        self, client: TestClient, brancher: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pauses: list[float] = []
        monkeypatch.setattr(service.time, "sleep", pauses.append)
        brancher["fhir"] = _FauxFhir([_condition("44054006")])

        client.post("/consulter", json={"patient": DANS_LA_DEMO})
        assert pauses == []


class TestRedactionIndisponible:
    def test_elle_remonte_dans_la_reponse_et_la_trace(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Un refus légitime et une rédaction coupée produisent la même issue.

        Sans ce drapeau, la démonstration présenterait une indisponibilité du fournisseur
        comme une décision de se taire — exactement la confusion que le moteur documentaire
        s'emploie à éviter.
        """
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        brancher["charge"] = {**REPONSE, "redaction_indisponible": True, "affirmations": []}

        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        requete = rendue["requetes"][0]
        assert requete["origine"] == "enregistrée", "la réponse enregistrée prend le relais"
        assert any("rédaction indisponible" in d["cause"] for d in rendue["degradations"])

        trace = client.get(f"/journal/{rendue['trace']}").json()
        assert trace["interrogations"][0]["origine"] == "enregistrée"


class TestApplicationDuContexte:
    def test_un_patient_hors_demonstration_est_refuse(self, client: TestClient) -> None:
        reponse = client.post("/consulter", json={"patient": "inconnu-9999"})
        assert reponse.status_code == 403

    def test_le_mode_smart_sans_jeton_est_refuse(self, client: TestClient) -> None:
        reponse = client.post("/consulter", json={"patient": DANS_LA_DEMO, "mode": "SMART"})
        assert reponse.status_code == 403

    def test_un_patient_hors_contexte_est_refuse_et_consigne(self, brancher: dict) -> None:
        """Le serveur amont ne l'applique pas ; ce refus n'a de trace nulle part ailleurs."""
        jeton = Jeton(access_token="j", scope="patient/Patient.read", patient=DANS_LA_DEMO)
        with pytest.raises(service.PatientRefuse):
            service.consulter(Consultation(patient=AUTRE, mode=Mode.SMART), jeton)

    def test_le_patient_du_contexte_est_accepte(self, brancher: dict) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        jeton = Jeton(access_token="j", scope="patient/Patient.read", patient=DANS_LA_DEMO)
        rendue, trace = service.consulter(
            Consultation(patient=DANS_LA_DEMO, mode=Mode.SMART), jeton
        )
        assert rendue.requetes
        assert trace.scopes_accordes == ["patient/Patient.read"]
        assert any(a.frontiere is Frontiere.DELEGUEE for a in trace.acces)


class TestJournal:
    def test_chaque_consultation_depose_une_trace(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        trace = client.get(f"/journal/{identifiant}").json()
        assert trace["identifiant"] == identifiant
        assert len(trace["interrogations"]) == 1

    def test_deux_pathologies_produisent_deux_interrogations_tracees(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Le défaut trouvé à l'essai réel, éprouvé de bout en bout.

        Avant correction, la trace ne gardait que la dernière question et lui attribuait les
        passages de la première — un journal qui affirmait le contraire de ce qui s'est passé.
        """
        brancher["fhir"] = _FauxFhir([_condition("44054006"), _condition("185086009")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        interrogations = client.get(f"/journal/{identifiant}").json()["interrogations"]

        assert [i["gabarit"] for i in interrogations] == ["diabete", "bpco"]
        assert len({i["question"] for i in interrogations}) == 2
        for interrogation in interrogations:
            assert interrogation["passages"], "chaque question garde ses propres passages"

    def test_la_trace_distingue_problemes_vus_et_retenus(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006"), _condition("444814009")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        problemes = client.get(f"/journal/{identifiant}").json()["problemes"]
        assert len(problemes) == 2
        assert sum(1 for p in problemes if p["dans_le_perimetre"]) == 1

    def test_les_deux_frontieres_figurent_dans_la_trace(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        acces = client.get(f"/journal/{identifiant}").json()["acces"]
        origines = {a["origine"] for a in acces}
        assert {"serveur FHIR", "documentaliste"} <= origines

    def test_une_trace_inconnue_rend_404(self, client: TestClient) -> None:
        assert client.get("/journal/inexistante").status_code == 404

    def test_la_trace_ne_porte_aucune_identite(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        rendu = client.get(f"/journal/{identifiant}").text
        for interdit in ("Stanton", "999-78-9632", "Schowalter"):
            assert interdit not in rendu
