"""Ce que le navigateur reçoit au retour d'un parcours d'autorisation.

Trois propriétés priment, et chacune répare un défaut que ce lot corrige :

- **le retour redirige, il ne rend jamais de JSON** — cette route est atteinte par une
  navigation, pas par un appel de la page : rendre un objet y laisserait le visiteur devant
  une accolade, succès comme échec ;
- **le texte d'erreur du serveur d'autorisation n'atteint jamais l'adresse de retour** — il
  est remplacé par un motif d'un vocabulaire fermé, sans quoi un tiers écrirait dans notre
  interface ;
- **`/smart/etat` ne rend pas le jeton** — il reste côté serveur, derrière un témoin
  `httponly`, et le publier le mettrait à portée de n'importe quel script de la page.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from passerelle.api import app as module
from passerelle.api.sessions import Sessions
from passerelle.smart.schemas import Demande, Jeton
from passerelle.terminologie.schemas import Concept

FRONT = "https://exemple.test/passerelle-fhir"
PATIENT = "bd6f9f37-7295-4cd6-b212-134afcef1253"
SESSION = "session-essai"


class _FausseTerminologie:
    """Le service éprouve la terminologie au démarrage ; sans ce double, la suite
    joindrait le serveur de l'ANS et cesserait d'être hors ligne."""

    def resoudre(self, systeme: str, code: str) -> Concept:
        return Concept(systeme=systeme, code=code, display="x", libelle_fr="x")

    def fermer(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Un service à l'adresse de retour connue, aux sessions vierges, et hors ligne."""
    from passerelle.api import service

    monkeypatch.setattr(service, "Terminologie", lambda *a, **k: _FausseTerminologie())
    monkeypatch.setattr(module, "sessions", Sessions())
    monkeypatch.setenv("PASSERELLE_FRONT", FRONT)
    monkeypatch.setenv("RATELIMIT_ENABLED", "false")
    with TestClient(module.app) as essai:
        yield essai


def _ouvrir(identifiant: str = SESSION) -> str:
    """Ouvre un parcours en cours, comme le ferait `/smart/lancer`."""
    demande = Demande(url="https://serveur.test/authorize", etat="e", verificateur="v")
    module.sessions.ouvrir(identifiant, demande)
    return identifiant


def _autoriser(client: TestClient, jeton: Jeton) -> None:
    """Amène le client à l'état « parcours abouti »."""
    identifiant = _ouvrir()
    module.sessions.deposer_jeton(identifiant, jeton)
    client.cookies.set(module.TEMOIN, identifiant)


def _retour(client: TestClient, **parametres: str) -> httpx.Response:
    return client.get("/smart/retour", params=parametres, follow_redirects=False)


def _issue(reponse: httpx.Response) -> dict[str, list[str]]:
    """Les paramètres de l'adresse vers laquelle le visiteur est renvoyé."""
    return parse_qs(urlparse(reponse.headers["location"]).query)


class TestRedirection:
    def test_un_refus_du_serveur_renvoie_sur_la_page(self, client: TestClient) -> None:
        reponse = _retour(client, error="access_denied")
        assert reponse.status_code == 302
        assert reponse.headers["location"].startswith(FRONT)

    def test_le_texte_du_serveur_n_atteint_pas_l_adresse(self, client: TestClient) -> None:
        """Le message vient d'un tiers : il part au journal, jamais dans l'adresse."""
        reponse = _retour(client, error="access_denied<script>alert(1)</script>")
        assert "script" not in reponse.headers["location"]
        assert _issue(reponse)["motif"] == ["refus"]

    def test_un_retour_sans_parcours_est_nomme(self, client: TestClient) -> None:
        """Témoin absent ou session expirée — un cas courant, pas une panne."""
        assert _issue(_retour(client, code="abc"))["motif"] == ["sans_parcours"]

    def test_un_echange_impossible_est_nomme(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def tomber(*_args: object, **_kwargs: object) -> None:
            raise module.DecouverteImpossible("injoignable")

        monkeypatch.setattr(module, "decouvrir", tomber)
        client.cookies.set(module.TEMOIN, _ouvrir())
        assert _issue(_retour(client, code="abc"))["motif"] == ["echange"]

    def test_aucune_issue_ne_rend_de_json(self, client: TestClient) -> None:
        """La propriété qui motive le lot : trois issues, trois redirections."""
        for parametres in ({"error": "x"}, {"code": "abc"}, {}):
            reponse = _retour(client, **parametres)
            assert reponse.status_code == 302, parametres


class TestMotifsFermes:
    def test_un_motif_non_declare_est_une_faute(self) -> None:
        """Le garde qui empêche de rouvrir le chemin par lequel un texte étranger passerait."""
        with pytest.raises(ValueError, match="motif non déclaré"):
            module._retour_au_front("motif-invente")

    def test_les_motifs_emis_sont_tous_declares(self, client: TestClient) -> None:
        emis: set[str] = set()
        for parametres in ({"error": "x"}, {"code": "abc"}):
            emis.update(_issue(_retour(client, **parametres)).get("motif", []))
        assert emis and emis <= module.MOTIFS

    def test_le_succes_ne_porte_pas_de_motif(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PASSERELLE_FRONT", FRONT)
        assert "motif" not in module._retour_au_front().headers["location"]


class TestEtat:
    def test_sans_session_l_etat_dit_non_autorise(self, client: TestClient) -> None:
        rendu = client.get("/smart/etat").json()
        assert rendu["autorisee"] is False
        assert rendu["contexte_patient"] == ""

    def test_l_etat_nomme_le_serveur_meme_sans_session(self, client: TestClient) -> None:
        """La page affiche contre quoi elle se connecterait, sans l'avoir codé en dur."""
        assert client.get("/smart/etat").json()["serveur"]

    def test_une_session_autorisee_rend_son_contexte(self, client: TestClient) -> None:
        _autoriser(client, Jeton(access_token="s", scope="patient/Patient.read", patient=PATIENT))
        rendu = client.get("/smart/etat").json()
        assert rendu["autorisee"] is True
        assert rendu["contexte_patient"] == PATIENT
        assert rendu["scopes"] == "patient/Patient.read"

    def test_le_jeton_n_apparait_nulle_part(self, client: TestClient) -> None:
        """La propriété de sécurité du lot, éprouvée sur la charge entière."""
        _autoriser(client, Jeton(access_token="secret-du-serveur", scope="s", patient=PATIENT))
        rendue = client.get("/smart/etat").text
        assert "secret-du-serveur" not in rendue
        assert "access_token" not in rendue


class TestChoixDuServeur:
    """Le serveur est nommé par son identifiant déclaré, jamais par son adresse.

    C'est la propriété qui empêche la falsification de requête côté serveur : accepter une
    base arbitraire en paramètre laisserait n'importe qui faire interroger n'importe quelle
    adresse par la passerelle.
    """

    def test_un_serveur_inconnu_est_refuse(self, client: TestClient) -> None:
        reponse = client.get("/smart/lancer", params={"serveur": "inconnu"}, follow_redirects=False)
        assert reponse.status_code == 400

    def test_une_adresse_passee_en_parametre_ne_devient_pas_une_base(
        self, client: TestClient
    ) -> None:
        """Le paramètre est un identifiant : une URL n'en est pas un, et est refusée."""
        reponse = client.get(
            "/smart/lancer",
            params={"serveur": "https://serveur-de-l-attaquant.test/fhir"},
            follow_redirects=False,
        )
        assert reponse.status_code == 400

    def test_le_perimetre_declare_les_serveurs_et_leur_posture(self, client: TestClient) -> None:
        serveurs = client.get("/perimetre").json()["serveurs"]
        assert serveurs, "aucun serveur déclaré, le test ne prouverait rien"
        assert all(serveur["posture"].strip() for serveur in serveurs)
        assert any(serveur["ouvert_au_public"] for serveur in serveurs)

    def test_aucune_adresse_n_est_publiee_a_la_page(self, client: TestClient) -> None:
        """La page nomme un serveur ; elle n'a pas besoin de son adresse pour ça.

        Une adresse publiée inviterait la page à s'en servir, et le contrat qui veut que la
        passerelle seule joigne les services extérieurs se relâcherait par cette porte.
        """
        for serveur in client.get("/perimetre").json()["serveurs"]:
            assert not any("://" in str(valeur) for valeur in serveur.values())

    def test_la_session_retient_la_base_du_serveur_choisi(self, client: TestClient) -> None:
        """Sinon le retour et la consultation liraient ailleurs que là où on a autorisé."""
        from passerelle.api.serveurs import SERVEURS

        identifiant = _ouvrir()
        module.sessions._sessions[identifiant].base = SERVEURS[1].base
        module.sessions.deposer_jeton(
            identifiant, Jeton(access_token="j", scope="s", patient=PATIENT)
        )
        client.cookies.set(module.TEMOIN, identifiant)
        rendu = client.get("/smart/etat").json()
        assert rendu["serveur"] == SERVEURS[1].base
        assert rendu["serveur_identifiant"] == SERVEURS[1].identifiant
