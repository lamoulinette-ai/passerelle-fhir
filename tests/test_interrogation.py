"""Ce qu'une condition désignée produit, et ce que la passerelle refuse de lire.

Deux propriétés priment :

- **une interrogation n'accepte qu'un code déjà présent dans sa trace** — sans cette
  contrainte, la route serait une recherche libre sur le corpus, détachée de tout dossier ;
- **un patient hors contexte est refusé par la passerelle et le refus est consigné** — le
  serveur amont, lui, ne l'applique pas : c'est le seul contrôle qui ait lieu.
"""

from __future__ import annotations

import pytest
from doubles import (
    AUTRE,
    DANS_LA_DEMO,
    REPONSE,
    FausseTerminologie,
    FauxFhir,
    condition,
    interroger,
)
from fastapi.testclient import TestClient

from passerelle.api import service
from passerelle.api.schemas import Consultation
from passerelle.journal.schemas import Frontiere, Mode
from passerelle.smart.schemas import Jeton


class TestInterrogation:
    def test_une_condition_du_perimetre_garde_sa_formulation_mesuree(
        self, client: TestClient, brancher: dict
    ) -> None:
        rendue = interroger(client, brancher, "44054006").json()
        assert rendue["requete"]["gabarit"] == "diabete"
        assert rendue["requete"]["codes"] == ["44054006"]
        assert rendue["requete"]["passages"]

    def test_une_condition_hors_perimetre_part_sur_la_forme_libre(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Le périmètre ne filtre plus rien : il distingue les questions préparées des autres."""
        brancher["terminologie"] = FausseTerminologie({"444814009": "infection virale"})
        rendue = interroger(client, brancher, "444814009").json()
        assert rendue["requete"]["gabarit"] == "444814009"
        assert "infection virale" in rendue["requete"]["texte"]

    def test_un_code_absent_du_dossier_est_refuse(self, client: TestClient, brancher: dict) -> None:
        """Sans cette borne, la route serait une recherche libre, détachée de tout dossier.

        C'est la trace qui fait office d'autorisation : elle atteste qu'un dossier a été lu
        et que ce code y figurait. Un code accepté sans elle romprait le lien entre la
        lecture et la question, qui est tout ce que le journal raconte.
        """
        brancher["fhir"] = FauxFhir([condition("44054006")])
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
        brancher["fhir"] = FauxFhir([condition("44054006"), condition("13645005")])
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
        brancher["fhir"] = FauxFhir([condition("44054006")])
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
        brancher["fhir"] = FauxFhir([condition("44054006")])
        trace = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        for _ in range(2):
            client.post("/interroger", json={"trace": trace, "code": "44054006"})

        assert len(brancher["appels"]) == 2, "la panne ne doit pas être mise en cache"

    def test_une_condition_sans_libelle_francais_est_signalee(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Poser une question anglaise à un corpus francophone doit se voir, pas se taire."""
        brancher["terminologie"] = FausseTerminologie(libelles={})
        rendue = interroger(client, brancher, "44054006").json()
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
        rendue = interroger(client, brancher, "44054006").json()
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
        brancher["fhir"] = FauxFhir([condition("44054006")])
        jeton = Jeton(access_token="j", scope="patient/Patient.read", patient=DANS_LA_DEMO)
        rendue, trace = service.consulter(
            Consultation(patient=DANS_LA_DEMO, mode=Mode.SMART), jeton
        )
        assert rendue.problemes
        assert trace.scopes_accordes == ["patient/Patient.read"]
        assert any(a.frontiere is Frontiere.DELEGUEE for a in trace.acces)


class TestJournal:
    def test_chaque_consultation_depose_une_trace(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = FauxFhir([condition("44054006")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        trace = client.get(f"/journal/{identifiant}").json()
        assert trace["identifiant"] == identifiant
        assert trace["interrogations"] == [], "une lecture seule n'a rien demandé"

    def test_la_trace_distingue_problemes_vus_et_retenus(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = FauxFhir([condition("44054006"), condition("444814009")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        problemes = client.get(f"/journal/{identifiant}").json()["problemes"]
        assert len(problemes) == 2
        assert sum(1 for p in problemes if p["dans_le_perimetre"]) == 1

    def test_les_deux_frontieres_figurent_dans_la_trace(
        self, client: TestClient, brancher: dict
    ) -> None:
        identifiant = interroger(client, brancher, "44054006").json()["trace"]
        acces = client.get(f"/journal/{identifiant}").json()["acces"]
        origines = {a["origine"] for a in acces}
        assert {"serveur FHIR", "documentaliste"} <= origines

    def test_une_trace_inconnue_rend_404(self, client: TestClient) -> None:
        assert client.get("/journal/inexistante").status_code == 404

    def test_la_trace_ne_porte_aucune_identite(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = FauxFhir([condition("44054006")])
        identifiant = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["trace"]
        rendu = client.get(f"/journal/{identifiant}").text
        for interdit in ("Stanton", "999-78-9632", "Schowalter"):
            assert interdit not in rendu
