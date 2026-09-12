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
from passerelle.api.serveurs import PAR_IDENTIFIANT as SERVEURS_PAR_ID
from passerelle.journal.schemas import Frontiere, Mode
from passerelle.smart.schemas import Jeton

#: Dossier publié par Oracle, absent du lanceur. Il éprouve que la déclaration est par serveur.
CHEZ_ORACLE = "12743119"


def _entetes_construits(
    monkeypatch: pytest.MonkeyPatch, demande: Consultation, jeton: Jeton | None = None
) -> dict[str, str] | None:
    """Les en-têtes avec lesquels le service a construit son client FHIR."""
    vus: dict[str, dict[str, str] | None] = {"entetes": None}
    construire = service.ClientFhir

    def espion(adresse: str | None = None, entetes: dict[str, str] | None = None) -> object:
        vus["entetes"] = entetes
        return construire(adresse=adresse, entetes=entetes)

    monkeypatch.setattr(service, "ClientFhir", espion)
    service.consulter(demande, jeton)
    return vus["entetes"]


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

    def test_un_jeton_sans_contexte_ouvre_les_dossiers_declares(self, brancher: dict) -> None:
        """Les portées `user/` n'ont pas de contexte patient : en exiger un fermerait tout."""
        brancher["fhir"] = FauxFhir([condition("44054006")])
        jeton = Jeton(access_token="j", scope="user/Patient.read user/Condition.read")
        rendue, _ = service.consulter(Consultation(patient=DANS_LA_DEMO, mode=Mode.SMART), jeton)
        assert rendue.problemes

    def test_un_jeton_sans_contexte_ne_franchit_pas_la_declaration(self, brancher: dict) -> None:
        """Le plancher du garde-fou : sans contexte, seule la liste du serveur autorise.

        Le dossier existe — chez Oracle — mais pas sur le serveur de cette consultation.
        """
        jeton = Jeton(access_token="j", scope="user/Patient.read")
        with pytest.raises(service.PatientRefuse):
            service.consulter(Consultation(patient=CHEZ_ORACLE, mode=Mode.SMART), jeton)

    def test_le_jeton_atteint_le_transport_et_pas_seulement_la_trace(
        self, brancher: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le serveur amont est le seul à pouvoir dire que l'en-tête manquait.

        Les doubles remplacent le client entier : sans ce test, un jeton obtenu, consigné et
        jamais envoyé laisse la suite au vert et se découvre en production.
        """
        brancher["fhir"] = FauxFhir([condition("44054006")])
        jeton = Jeton(access_token="secret", scope="user/Patient.read")
        entetes = _entetes_construits(
            monkeypatch, Consultation(patient=DANS_LA_DEMO, mode=Mode.SMART), jeton
        )
        assert entetes == {"Authorization": "Bearer secret"}

    def test_sans_autorisation_aucun_en_tete_n_est_construit(
        self, brancher: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        brancher["fhir"] = FauxFhir([condition("44054006")])
        assert _entetes_construits(monkeypatch, Consultation(patient=DANS_LA_DEMO)) is None

    def test_le_meme_dossier_s_ouvre_sur_le_serveur_qui_le_declare(self, brancher: dict) -> None:
        """La déclaration est par serveur : le refus précédent tient au serveur, pas au dossier."""
        brancher["fhir"] = FauxFhir([condition("44054006")])
        rendue, _ = service.consulter(
            Consultation(patient=CHEZ_ORACLE),
            serveur=SERVEURS_PAR_ID["oracle_ouvert"],
        )
        assert rendue.problemes

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

    def test_la_trace_dit_la_formulation_de_chaque_probleme(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Les deux sont consignés et interrogeables ; seule leur tournure diffère."""
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
