"""Ce que le service rend d'un dossier, et ce qu'il refuse.

Trois propriétés valent tous les autres tests de ce fichier :

- **une consultation ne pose aucune question** — elle lit un dossier et le rend ; c'est
  l'utilisateur qui désigne ensuite la condition qui l'intéresse ;
- **`/health` suit la dernière résolution réelle, pas la sonde de démarrage** — un drapeau
  mesuré une seule fois ment par immobilité, ce qui s'est produit en production ;
- **une consultation dégradée rend un résultat et une trace qui nomme les causes** — sans
  quoi un service en panne serait indiscernable d'un dossier vide.

Les interrogations du corpus sont éprouvées dans `test_interrogation.py`.
"""

from __future__ import annotations

from doubles import (
    DANS_LA_DEMO,
    ICD10CM,
    FausseTerminologie,
    FauxFhir,
    condition,
    interroger,
)
from fastapi.testclient import TestClient


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
        brancher["terminologie"] = FausseTerminologie(tombe=True)
        from passerelle.api.app import app

        with TestClient(app) as essai:
            etat = essai.get("/health").json()
        assert etat["debout"] is True
        assert etat["complet"] is False
        assert "injoignable" in etat["terminologie"]

    def test_une_consultation_revise_ce_que_le_demarrage_avait_constate(
        self, brancher: dict
    ) -> None:
        """Le drapeau suit la dernière résolution réelle, pas la sonde de démarrage.

        Mesuré une seule fois, il mentait par immobilité : une indisponibilité de trente
        secondes au démarrage le figeait à « injoignable » pendant des jours, alors que le
        service résolvait correctement à chaque requête. Constaté en production.
        """
        brancher["terminologie"] = FausseTerminologie(tombe=True)
        from passerelle.api.app import app

        with TestClient(app) as essai:
            assert essai.get("/health").json()["complet"] is False

            # Le serveur revient, et une consultation ordinaire le constate.
            brancher["terminologie"] = FausseTerminologie()
            brancher["fhir"] = FauxFhir([condition("44054006")])
            essai.post("/consulter", json={"patient": DANS_LA_DEMO})

            etat = essai.get("/health").json()
        assert etat["complet"] is True
        assert etat["terminologie"] == "disponible"
        assert etat["terminologie_vue"], "l'instant de l'observation est rendu"

    def test_une_panne_survenue_apres_le_demarrage_se_dit(
        self, client: TestClient, brancher: dict
    ) -> None:
        """L'inverse tient : un démarrage réussi ne masque pas une panne survenue depuis."""
        assert client.get("/health").json()["complet"] is True

        brancher["terminologie"] = FausseTerminologie(tombe=True)
        brancher["fhir"] = FauxFhir([condition("44054006")])
        client.post("/consulter", json={"patient": DANS_LA_DEMO})

        assert client.get("/health").json()["complet"] is False

    def test_un_dossier_sans_probleme_n_apprend_rien(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Rien n'a été demandé à la terminologie : l'observation précédente doit tenir."""
        brancher["fhir"] = FauxFhir([])
        client.post("/consulter", json={"patient": DANS_LA_DEMO})
        assert client.get("/health").json()["complet"] is True


class TestPerimetre:
    def test_chaque_patient_annonce_ses_serveurs(self, client: TestClient) -> None:
        """Un identifiant ne vaut que sur le serveur qui le publie ; la page doit le savoir."""
        patients = client.get("/perimetre").json()["patients"]
        assert len([p for p in patients if "lanceur" in p["serveurs"]]) == 4
        assert len([p for p in patients if "oracle_ouvert" in p["serveurs"]]) == 3
        assert all(p["serveurs"] for p in patients), "aucun dossier sans serveur"

    def test_un_serveur_sans_couche_d_autorisation_est_annonce_tel_quel(
        self, client: TestClient
    ) -> None:
        """La page n'a pas de connexion à proposer pour lui, et donc rien à griser."""
        serveurs = {s["identifiant"]: s for s in client.get("/perimetre").json()["serveurs"]}
        assert serveurs["oracle_ouvert"]["lecture_directe"] is True
        assert serveurs["oracle_securise"]["lecture_directe"] is False

    def test_aucune_pathologie_n_est_annoncee(self, client: TestClient) -> None:
        """En annoncer trois laissait croire que la démonstration ne portait que sur elles."""
        assert "pathologies" not in client.get("/perimetre").json()

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


class TestReferentielNonHeberge:
    """Le serveur français n'héberge pas tous les référentiels du monde, et le dit vite."""

    def _consulter(self, client: TestClient, brancher: dict) -> dict:
        brancher["fhir"] = FauxFhir([condition("44054006"), condition("I11.0", systeme=ICD10CM)])
        brancher["terminologie"] = FausseTerminologie(inconnus={ICD10CM})
        return client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()

    def test_un_code_inconnu_ne_coute_pas_les_autres_libelles(
        self, client: TestClient, brancher: dict
    ) -> None:
        """La régression qui comptait : un seul code américain vidait tout le dossier."""
        problemes = {p["code"]: p for p in self._consulter(client, brancher)["problemes"]}
        assert problemes["44054006"]["libelle_fr"] == "diabète de type 2"
        assert problemes["I11.0"]["libelle_fr"] is None

    def test_la_degradation_ne_parle_pas_de_panne(self, client: TestClient, brancher: dict) -> None:
        causes = [d["cause"] for d in self._consulter(client, brancher)["degradations"]]
        assert any("hors des référentiels" in cause for cause in causes)
        assert not any("injoignable" in cause for cause in causes)

    def test_la_terminologie_reste_disponible(self, client: TestClient, brancher: dict) -> None:
        """Elle a répondu. L'inscrire injoignable dans `/health` serait un second mensonge."""
        self._consulter(client, brancher)
        assert client.get("/health").json()["complet"] is True


class TestServeurDesigne:
    """La page nomme un serveur déclaré, jamais une adresse."""

    def test_un_serveur_inconnu_est_refuse(self, client: TestClient) -> None:
        reponse = client.post(
            "/consulter", json={"patient": DANS_LA_DEMO, "serveur": "chez-l-attaquant"}
        )
        assert reponse.status_code == 400

    def test_une_adresse_ne_passe_pas_pour_un_identifiant(self, client: TestClient) -> None:
        """La garde tient sur la forme aussi : une base n'est jamais un identifiant déclaré."""
        reponse = client.post(
            "/consulter",
            json={"patient": DANS_LA_DEMO, "serveur": "https://serveur-de-l-attaquant.test/fhir"},
        )
        assert reponse.status_code == 400

    def test_un_serveur_absent_vaut_le_serveur_par_defaut(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = FauxFhir([condition("44054006")])
        assert client.post("/consulter", json={"patient": DANS_LA_DEMO}).status_code == 200

    def test_un_dossier_oracle_s_ouvre_sur_le_serveur_oracle(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = FauxFhir([condition("44054006")])
        reponse = client.post(
            "/consulter", json={"patient": "12743119", "serveur": "oracle_ouvert"}
        )
        assert reponse.status_code == 200

    def test_le_meme_dossier_est_refuse_sur_le_lanceur(self, client: TestClient) -> None:
        assert client.post("/consulter", json={"patient": "12743119"}).status_code == 403


class TestConsultation:
    def test_la_consultation_ne_pose_aucune_question(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Lire un dossier et interroger un corpus sont deux gestes distincts.

        La passerelle ne choisit plus ce qui mérite d'être demandé : elle rend ce qu'elle a
        lu, et attend que l'utilisateur désigne une condition.
        """
        brancher["fhir"] = FauxFhir([condition("44054006"), condition("13645005")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert "requetes" not in rendue, "le champ n'existe plus : il était toujours vide"
        assert brancher["appels"] == [], "aucun appel au moteur documentaire"
        assert len(rendue["problemes"]) == 2
        assert rendue["trace"]

    def test_un_probleme_hors_perimetre_est_rendu_et_signale(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Hors périmètre ne veut plus dire écarté : seulement « sans question préparée »."""
        brancher["fhir"] = FauxFhir([condition("444814009")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert len(rendue["problemes"]) == 1
        assert rendue["problemes"][0]["dans_le_perimetre"] is False

    def test_une_condition_resolue_garde_son_statut(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = FauxFhir([condition("44054006", "resolved")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["problemes"][0]["statut"] == "resolved"

    def test_l_age_est_calcule(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = FauxFhir([])
        assert client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()["age"] >= 68


class TestDegradation:
    def test_le_libelle_francais_est_rendu(self, client: TestClient, brancher: dict) -> None:
        brancher["fhir"] = FauxFhir([condition("44054006")])
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["problemes"][0]["libelle_fr"] == "diabète de type 2"
        assert rendue["degradations"] == []

    def test_une_terminologie_injoignable_degrade_sans_vider(
        self, client: TestClient, brancher: dict
    ) -> None:
        """Les codes restent bruts, les problèmes sont rendus, et la cause est nommée."""
        brancher["fhir"] = FauxFhir([condition("44054006")])
        brancher["terminologie"] = FausseTerminologie(tombe=True)

        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["problemes"], "le contexte lu ne doit pas disparaître"
        assert rendue["problemes"][0]["libelle_fr"] is None
        assert any("terminologies" in d["cause"] for d in rendue["degradations"])

    def test_un_code_non_traduit_reste_non_resolu(self, client: TestClient, brancher: dict) -> None:
        """Le serveur rend un `display` même sans traduction ; il ne compte pas comme résolu."""
        brancher["fhir"] = FauxFhir([condition("15777000")])
        brancher["terminologie"] = FausseTerminologie(libelles={})

        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["problemes"][0]["libelle_fr"] is None

    def test_un_moteur_en_panne_degrade_sans_vider(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["statut"], brancher["charge"] = 503, {}
        rendue = interroger(client, brancher, "44054006").json()
        assert rendue["requete"]["origine"] == "enregistrée"
        assert any("503" in d["cause"] for d in rendue["degradations"])

    def test_un_serveur_fhir_injoignable_rend_une_trace(
        self, client: TestClient, brancher: dict
    ) -> None:
        brancher["fhir"] = FauxFhir(tombe=True)
        rendue = client.post("/consulter", json={"patient": DANS_LA_DEMO}).json()
        assert rendue["trace"]
        assert rendue["problemes"] == []
        assert any("FHIR" in d["cause"] for d in rendue["degradations"])
