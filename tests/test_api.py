"""Ce que le service rend, et ce qu'il refuse.

Cinq propriétés valent tous les autres tests de ce fichier :

- **une consultation ne pose aucune question** — elle lit un dossier et le rend ; c'est
  l'utilisateur qui désigne ensuite la condition qui l'intéresse ;
- **une interrogation n'accepte qu'un code déjà présent dans sa trace** — sans cette
  contrainte, la route serait une recherche libre sur le corpus, détachée de tout dossier ;
- **une consultation dégradée rend un résultat et une trace qui nomme les causes** — sans
  quoi une clé absente et un service en panne seraient indiscernables d'un dossier vide ;
- **un patient hors contexte est refusé par la passerelle et le refus est consigné** — le
  serveur amont, lui, ne l'applique pas : c'est le seul contrôle qui ait lieu ;
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
from passerelle.smart.decouverte import DecouverteImpossible
from passerelle.smart.schemas import Jeton
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


class _FausseTerminologie:
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
    reglages: dict = {
        "fhir": _FauxFhir(),
        "statut": 200,
        "charge": REPONSE,
        "terminologie": _FausseTerminologie(),
        "joignable": True,
        "appels": [],
    }

    def fhir(*_a: object, **_k: object) -> _FauxFhir:
        return reglages["fhir"]

    def documentaliste(*_a: object, **_k: object) -> Documentaliste:
        def repondre(requete: httpx.Request) -> httpx.Response:
            reglages["appels"].append(str(requete.url))
            return httpx.Response(reglages["statut"], json=reglages["charge"])

        return _faux_documentaliste(repondre)

    def terminologie(*_a: object, **_k: object) -> _FausseTerminologie:
        return reglages["terminologie"]

    def decouvrir(base: str, *_a: object, **_k: object) -> object:
        if not reglages["joignable"]:
            raise DecouverteImpossible(f"{base} : injoignable")
        return object()

    monkeypatch.setattr(service, "ClientFhir", fhir)
    monkeypatch.setattr(service, "Documentaliste", documentaliste)
    # Le service éprouve la terminologie au démarrage : sans ce double, le `TestClient`
    # joindrait le serveur de l'ANS et la suite cesserait d'être hors ligne.
    monkeypatch.setattr(service, "Terminologie", terminologie)
    # Même raison pour les trois serveurs FHIR, éprouvés eux aussi au démarrage.
    monkeypatch.setattr(service, "decouvrir", decouvrir)
    # Le cache est un état de module : sans ce vidage, l'ordre des tests déciderait de leur
    # résultat, et celui qui compte les appels au moteur passerait ou non selon ses voisins.
    service.CACHE.clear()
    monkeypatch.delenv("PASSERELLE_SMT_CLE", raising=False)
    monkeypatch.setenv("RATELIMIT_ENABLED", "false")
    yield reglages
    service.CACHE.clear()


def _interroger(client: TestClient, brancher: dict, code: str) -> httpx.Response:
    """Consulte un dossier portant ce seul code, puis désigne ce code — comme le ferait la page."""
    brancher["fhir"] = _FauxFhir([_condition(code)])
    trace = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
    return client.post("/interroger", json={"trace": trace, "code": code})


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

    def test_une_terminologie_qui_repond_rend_le_service_complet(self, client: TestClient) -> None:
        etat = client.get("/health").json()
        assert etat["debout"] is True
        assert etat["complet"] is True
        assert etat["terminologie"] == "disponible"

    def test_une_terminologie_injoignable_se_dit(self, brancher: dict) -> None:
        """« Je réponds » et « je réponds complètement » restent deux choses différentes.

        L'état est éprouvé au démarrage sur un concept témoin, jamais déduit de la présence
        d'une clé : `$lookup` répond sans authentification.
        """
        brancher["terminologie"] = _FausseTerminologie(tombe=True)
        from passerelle.api.app import app

        with TestClient(app) as essai:
            etat = essai.get("/health").json()
        assert etat["debout"] is True
        assert etat["complet"] is False
        assert "injoignable" in etat["terminologie"]


class TestPerimetre:
    def test_les_patients_et_pathologies_sont_annonces(self, client: TestClient) -> None:
        charge = client.get("/perimetre").json()
        assert len(charge["patients"]) == 5
        assert len(charge["pathologies"]) == 3

    def test_l_avertissement_est_rendu_par_l_api(self, client: TestClient) -> None:
        """Il ne doit pas être écrit dans la page : on pourrait l'y oublier."""
        assert "dispositif médical" in client.get("/perimetre").json()["avertissement"]

    def test_un_serveur_qui_repond_est_dit_joignable(self, client: TestClient) -> None:
        charge = client.get("/perimetre").json()
        assert all(serveur["joignable"] for serveur in charge["serveurs"])
        assert charge["degradee"] is False

    def test_aucun_serveur_joignable_degrade_la_demonstration(self, brancher: dict) -> None:
        """La page a besoin de le savoir **avant** de proposer une connexion.

        Présenter trois boutons dont aucun n'aboutit ferait porter à l'utilisateur le
        diagnostic d'une panne que le service connaissait déjà à son démarrage.
        """
        brancher["joignable"] = False
        from passerelle.api.app import app

        with TestClient(app) as essai:
            charge = essai.get("/perimetre").json()
        assert not any(serveur["joignable"] for serveur in charge["serveurs"])
        assert charge["degradee"] is True


class TestConsultation:
    def test_la_consultation_ne_pose_aucune_question(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Lire un dossier et interroger un corpus sont deux gestes distincts.

        La passerelle ne choisit plus ce qui mérite d'être demandé : elle rend ce qu'elle a
        lu, et attend que l'utilisateur désigne une condition.
        """
        brancher["fhir"] = _FauxFhir([_condition("44054006"), _condition("13645005")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert "requetes" not in rendue, "le champ n'existe plus : il était toujours vide"
        assert brancher["appels"] == [], "aucun appel au moteur documentaire"
        assert len(rendue["problemes"]) == 2
        assert rendue["trace"]

    def test_un_probleme_hors_perimetre_est_rendu_et_signale(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Hors périmètre ne veut plus dire écarté : seulement « sans question préparée »."""
        brancher["fhir"] = _FauxFhir([_condition("444814009")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert len(rendue["problemes"]) == 1
        assert rendue["problemes"][0]["dans_le_perimetre"] is False

    def test_une_condition_resolue_garde_son_statut(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006", "resolved")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["problemes"][0]["statut"] == "resolved"

    def test_l_age_est_calcule(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = _FauxFhir([])
        assert client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["age"] >= 68


class TestDegradation:
    def test_le_libelle_francais_est_rendu(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["problemes"][0]["libelle_fr"] == "diabète de type 2"
        assert rendue["degradations"] == []

    def test_une_terminologie_injoignable_degrade_sans_vider(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Les codes restent bruts, les problèmes sont rendus, et la cause est nommée."""
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        brancher["terminologie"] = _FausseTerminologie(tombe=True)

        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["problemes"], "le contexte lu ne doit pas disparaître"
        assert rendue["problemes"][0]["libelle_fr"] is None
        assert any("terminologies" in d["cause"] for d in rendue["degradations"])

    def test_un_code_non_traduit_reste_non_resolu(self, client: TestClient, brancher: dict) -> None:
        """Le serveur rend un `display` même sans traduction ; il ne compte pas comme résolu."""
        brancher["fhir"] = _FauxFhir([_condition("15777000")])
        brancher["terminologie"] = _FausseTerminologie(libelles={})

        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["problemes"][0]["libelle_fr"] is None

    def test_un_moteur_en_panne_degrade_sans_vider(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["statut"], brancher["charge"] = 503, {}
        rendue = _interroger(client, brancher, "44054006").json()
        assert rendue["requete"]["origine"] == "enregistrée"
        assert any("503" in d["cause"] for d in rendue["degradations"])

    def test_un_serveur_fhir_injoignable_rend_une_trace(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = _FauxFhir(tombe=True)
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["trace"]
        assert rendue["problemes"] == []
        assert any("FHIR" in d["cause"] for d in rendue["degradations"])


class TestInterrogation:
    def test_une_condition_du_perimetre_garde_sa_formulation_mesuree(
        self, client: TestClient, brancher: dict
    ) -> None:
        rendue = _interroger(client, brancher, "44054006").json()
        assert rendue["requete"]["gabarit"] == "diabete"
        assert rendue["requete"]["codes"] == ["44054006"]
        assert rendue["requete"]["passages"]

    def test_une_condition_hors_perimetre_part_sur_la_forme_libre(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Le périmètre ne filtre plus rien : il distingue les questions préparées des autres."""
        brancher["terminologie"] = _FausseTerminologie({"444814009": "infection virale"})
        rendue = _interroger(client, brancher, "444814009").json()
        assert rendue["requete"]["gabarit"] == "444814009"
        assert "infection virale" in rendue["requete"]["texte"]

    def test_un_code_absent_du_dossier_est_refuse(self, client: TestClient, brancher: dict) -> None:
        """Sans cette borne, la route serait une recherche libre, détachée de tout dossier.

        C'est la trace qui fait office d'autorisation : elle atteste qu'un dossier a été lu
        et que ce code y figurait. Un code accepté sans elle romprait le lien entre la
        lecture et la question, qui est tout ce que le journal raconte.
        """
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        trace = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        reponse = client.post("/interroger", json={"trace": trace, "code": "13645005"})
        assert reponse.status_code == 400
        assert brancher["appels"] == [], "le moteur ne doit pas avoir été appelé"

    def test_une_trace_inconnue_rend_404(self, client: TestClient) -> None:
        reponse = client.post("/interroger", json={"trace": "inexistante", "code": "44054006"})
        assert reponse.status_code == 404

    def test_la_question_s_ajoute_a_la_trace_de_la_consultation(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Une trace par consultation, pas une par question.

        Ouvrir une trace neuve à chaque question perdrait le lien entre la lecture du dossier
        et ce qu'elle a permis de demander — précisément ce qu'un auditeur vient chercher.
        """
        brancher["fhir"] = _FauxFhir([_condition("44054006"), _condition("13645005")])
        trace = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        for code in ("44054006", "13645005"):
            client.post("/interroger", json={"trace": trace, "code": code})

        interrogations = client.get(f"/journal/{trace}").json()["interrogations"]
        assert [i["gabarit"] for i in interrogations] == ["diabete", "bpco"]
        assert len({i["question"] for i in interrogations}) == 2
        for interrogation in interrogations:
            assert interrogation["passages"], "chaque question garde ses propres passages"

    def test_la_meme_question_n_est_posee_qu_une_fois(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Le corpus ne change pas d'un visiteur à l'autre.

        Sans ce cache, une démonstration publique épuiserait en trois minutes les vingt
        questions par heure que le moteur documentaire accorde par adresse — et la passerelle
        l'appelle depuis une seule.
        """
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        trace = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        for _ in range(3):
            client.post("/interroger", json={"trace": trace, "code": "44054006"})

        assert len(brancher["appels"]) == 1
        acces = client.get(f"/journal/{trace}").json()["acces"]
        assert sum(1 for a in acces if a["origine"] == "cache") == 2

    def test_une_reponse_degradee_n_est_pas_retenue(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Servir plus tard un refus dû à une panne passagère figerait l'indisponibilité."""
        brancher["statut"], brancher["charge"] = 503, {}
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        trace = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        for _ in range(2):
            client.post("/interroger", json={"trace": trace, "code": "44054006"})

        assert len(brancher["appels"]) == 2, "la panne ne doit pas être mise en cache"

    def test_une_condition_sans_libelle_francais_est_signalee(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Poser une question anglaise à un corpus francophone doit se voir, pas se taire."""
        brancher["terminologie"] = _FausseTerminologie(libelles={})
        rendue = _interroger(client, brancher, "44054006").json()
        assert any("désignation française" in d["cause"] for d in rendue["degradations"])

    def test_la_redaction_indisponible_remonte_dans_la_reponse_et_la_trace(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Un refus légitime et une rédaction coupée produisent la même issue.

        Sans ce drapeau, la démonstration présenterait une indisponibilité du fournisseur
        comme une décision de se taire — exactement la confusion que le moteur documentaire
        s'emploie à éviter.
        """
        brancher["charge"] = {**REPONSE, "redaction_indisponible": True, "affirmations": []}
        rendue = _interroger(client, brancher, "44054006").json()
        assert rendue["requete"]["origine"] == "enregistrée", "l'enregistrée prend le relais"
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
        assert rendue.problemes
        assert trace.scopes_accordes == ["patient/Patient.read"]
        assert any(a.frontiere is Frontiere.DELEGUEE for a in trace.acces)


class TestJournal:
    def test_chaque_consultation_depose_une_trace(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = _FauxFhir([_condition("44054006")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        trace = client.get(f"/journal/{identifiant}").json()
        assert trace["identifiant"] == identifiant
        assert trace["interrogations"] == [], "une lecture seule n'a rien demandé"

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
        identifiant = _interroger(client, brancher, "44054006").json()["trace"]
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
