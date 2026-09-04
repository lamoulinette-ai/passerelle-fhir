"""L'autorisation SMART, éprouvée sans réseau.

Trois propriétés valent tous les autres tests de ce fichier :

- **le `code_challenge` est bien l'empreinte du vérificateur** — s'il ne l'était pas,
  l'échange serait refusé par le serveur, et la panne se chercherait dans la configuration
  du client au lieu du calcul ;
- **un `state` discordant est refusé** — c'est la seule protection contre un code injecté
  par un tiers, et rien dans la réponse d'un serveur ne signale son absence ;
- **aucun point d'entrée n'est câblé en dur** — tous viennent de la configuration découverte,
  faute de quoi le client ne fonctionnerait que contre le serveur qui a servi à l'écrire.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from passerelle.smart.autorisation import (
    AutorisationRefusee,
    demander,
    echanger,
    empreinte,
    verificateur,
)
from passerelle.smart.decouverte import DecouverteImpossible, decouvrir
from passerelle.smart.schemas import ConfigurationSmart, Demande

EXEMPLES = Path(__file__).parent / "exemples"
Gestionnaire = Callable[[httpx.Request], httpx.Response]

REDIRECTION = "https://fhir.lamoulinette.ai/smart/retour"
BASE = "https://exemple.test/fhir"


def _client(gestionnaire: Gestionnaire) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(gestionnaire))


@pytest.fixture
def configuration() -> ConfigurationSmart:
    charge = json.loads((EXEMPLES / "smart_configuration.json").read_text(encoding="utf-8"))
    return ConfigurationSmart.model_validate(charge)


class TestDecouverte:
    def test_les_points_d_entree_sont_lus(self, configuration: ConfigurationSmart) -> None:
        assert configuration.authorization_endpoint.endswith("/auth/authorize")
        assert configuration.token_endpoint.endswith("/auth/token")

    def test_les_capacites_sont_interpretees(self, configuration: ConfigurationSmart) -> None:
        assert configuration.pkce_s256
        assert configuration.lancement_autonome

    def test_le_chemin_bien_connu_est_interroge(self) -> None:
        vues: list[str] = []

        def repondre(requete: httpx.Request) -> httpx.Response:
            vues.append(requete.url.path)
            return httpx.Response(200, json={"authorization_endpoint": "a", "token_endpoint": "b"})

        decouvrir(BASE, client=_client(repondre))
        assert vues == ["/fhir/.well-known/smart-configuration"]

    def test_une_configuration_incomplete_est_refusee(self) -> None:
        """Sans point d'entrée de jeton, le parcours échouerait à l'échange, pas au départ."""

        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"authorization_endpoint": "a"})

        with pytest.raises(DecouverteImpossible):
            decouvrir(BASE, client=_client(repondre))

    def test_une_absence_de_configuration_est_refusee(self) -> None:
        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        with pytest.raises(DecouverteImpossible):
            decouvrir(BASE, client=_client(repondre))


class TestPkce:
    def test_l_empreinte_est_le_sha256_du_verificateur(self) -> None:
        verif = verificateur()
        attendu = base64.urlsafe_b64encode(hashlib.sha256(verif.encode()).digest())
        assert empreinte(verif) == attendu.decode().rstrip("=")

    def test_l_empreinte_ne_porte_pas_de_bourrage(self) -> None:
        """RFC 7636 impose le base64url sans `=` ; un serveur strict refuse le contraire."""
        assert "=" not in empreinte(verificateur())

    def test_deux_verificateurs_different(self) -> None:
        assert verificateur() != verificateur()


class TestDemande:
    def test_l_url_part_du_point_d_entree_decouvert(
        self, configuration: ConfigurationSmart
    ) -> None:
        demande = demander(configuration, BASE, REDIRECTION)
        assert demande.url.startswith(configuration.authorization_endpoint)

    def test_les_parametres_obligatoires_sont_presents(
        self, configuration: ConfigurationSmart
    ) -> None:
        url = httpx.URL(demander(configuration, BASE, REDIRECTION).url)
        for attendu in ("response_type", "client_id", "scope", "redirect_uri", "aud", "state"):
            assert attendu in url.params
        assert url.params["code_challenge_method"] == "S256"
        assert url.params["aud"] == BASE

    def test_le_verificateur_ne_part_pas_dans_l_url(
        self, configuration: ConfigurationSmart
    ) -> None:
        """Seule l'empreinte voyage : c'est tout l'intérêt de PKCE."""
        demande = demander(configuration, BASE, REDIRECTION)
        assert demande.verificateur not in demande.url

    def test_le_defi_correspond_au_verificateur(self, configuration: ConfigurationSmart) -> None:
        demande = demander(configuration, BASE, REDIRECTION)
        url = httpx.URL(demande.url)
        assert url.params["code_challenge"] == empreinte(demande.verificateur)

    def test_le_lancement_est_joint_quand_il_existe(
        self, configuration: ConfigurationSmart
    ) -> None:
        url = httpx.URL(demander(configuration, BASE, REDIRECTION, lancement="xyz").url)
        assert url.params["launch"] == "xyz"

    def test_le_lancement_est_absent_sinon(self, configuration: ConfigurationSmart) -> None:
        url = httpx.URL(demander(configuration, BASE, REDIRECTION).url)
        assert "launch" not in url.params


class TestEchange:
    def _demande(self) -> Demande:
        verif = verificateur()
        return Demande(url="https://exemple.test/auth", etat="etat-connu", verificateur=verif)

    def test_un_jeton_est_rendu(self, configuration: ConfigurationSmart) -> None:
        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "access_token": "jeton",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "patient/Condition.read",
                    "patient": "patient-1",
                },
            )

        jeton = echanger(
            configuration, self._demande(), "code", "etat-connu", REDIRECTION, _client(repondre)
        )
        assert jeton.patient == "patient-1"
        assert jeton.entete["Authorization"] == "Bearer jeton"
        assert jeton.scopes == ["patient/Condition.read"]

    def test_le_verificateur_est_envoye(self, configuration: ConfigurationSmart) -> None:
        demande = self._demande()
        corps: list[bytes] = []

        def repondre(requete: httpx.Request) -> httpx.Response:
            corps.append(requete.content)
            return httpx.Response(200, json={"access_token": "jeton"})

        echanger(configuration, demande, "code", "etat-connu", REDIRECTION, _client(repondre))
        assert f"code_verifier={demande.verificateur}".encode() in corps[0]

    def test_un_etat_discordant_est_refuse(self, configuration: ConfigurationSmart) -> None:
        """Aucune requête ne doit partir : le refus précède l'échange."""
        appels: list[int] = []

        def repondre(_requete: httpx.Request) -> httpx.Response:
            appels.append(1)
            return httpx.Response(200, json={"access_token": "jeton"})

        with pytest.raises(AutorisationRefusee):
            echanger(
                configuration, self._demande(), "code", "autre", REDIRECTION, _client(repondre)
            )
        assert appels == []

    def test_une_erreur_oauth_est_refusee(self, configuration: ConfigurationSmart) -> None:
        """Certains serveurs rendent 200 avec un corps d'erreur : le statut ne suffit pas."""

        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "invalid_grant"})

        with pytest.raises(AutorisationRefusee):
            echanger(
                configuration, self._demande(), "code", "etat-connu", REDIRECTION, _client(repondre)
            )

    def test_un_refus_http_est_refuse(self, configuration: ConfigurationSmart) -> None:
        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "invalid_request"})

        with pytest.raises(AutorisationRefusee):
            echanger(
                configuration, self._demande(), "code", "etat-connu", REDIRECTION, _client(repondre)
            )
