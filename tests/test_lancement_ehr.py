"""Le parcours d'autorisation ouvert depuis un dossier patient.

Trois propriétés priment, et la première est une propriété de sécurité :

- **l'adresse annoncée par le dossier est ramenée à un serveur déclaré avant toute requête
  sortante** — c'est la garde de `/smart/lancer`, transposée d'un identifiant à une adresse.
  Sans elle, la route ferait interroger n'importe quelle adresse par la passerelle ;
- **un lancement sans contexte est refusé ici** — le laisser passer produirait chez le
  serveur d'autorisation un refus que plus rien, ensuite, ne saurait expliquer ;
- **les deux modes ne demandent pas les mêmes scopes** — `launch` quand le dossier fournit
  le contexte, `launch/patient` quand il faut que le serveur d'autorisation le désigne ;
- **et les serveurs non plus** — un serveur qui ne propose pas de sélecteur de patient ne
  peut pas se voir demander `patient/`, qui ne désignerait rien.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from passerelle.api import app as module
from passerelle.api.serveurs import PAR_IDENTIFIANT
from passerelle.api.sessions import Sessions
from passerelle.smart.schemas import ConfigurationSmart

SECURISE = PAR_IDENTIFIANT["oracle_securise"]
LANCEUR = PAR_IDENTIFIANT["lanceur"]
LANCEMENT = "jeton-de-lancement"

CONFIGURATION = ConfigurationSmart(
    authorization_endpoint="https://serveur.test/authorize",
    token_endpoint="https://serveur.test/token",
    code_challenge_methods_supported=["S256"],
)


@pytest.fixture
def visites(brancher: dict, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Les bases dont la configuration a été demandée, sessions vierges et hors ligne.

    La découverte est comptée plutôt que simplement neutralisée : le refus d'une adresse non
    déclarée ne vaut que si aucune requête n'est partie vers elle.
    """
    demandees: list[str] = []

    def decouvrir(base: str, *_a: object, **_k: object) -> ConfigurationSmart:
        demandees.append(base)
        return CONFIGURATION

    monkeypatch.setattr(module, "decouvrir", decouvrir)
    monkeypatch.setattr(module, "sessions", Sessions())
    yield demandees


@pytest.fixture
def client(visites: list[str]) -> Iterator[TestClient]:
    assert visites is not None, "la découverte doit être comptée avant le service"
    with TestClient(module.app) as essai:
        yield essai


def _lancer(client: TestClient, **parametres: str) -> httpx.Response:
    return client.get("/smart/ehr", params=parametres, follow_redirects=False)


def _demande(reponse: httpx.Response) -> dict[str, list[str]]:
    """Les paramètres de l'adresse d'autorisation vers laquelle le dossier est renvoyé."""
    return parse_qs(urlparse(reponse.headers["location"]).query)


class TestAdresseAnnonceeParLeDossier:
    """`iss` vient de l'extérieur : il est apparié, jamais suivi."""

    def test_une_adresse_non_declaree_est_refusee(
        self, client: TestClient, visites: list[str]
    ) -> None:
        reponse = _lancer(client, iss="https://serveur-de-l-attaquant.test/fhir", launch=LANCEMENT)
        assert reponse.status_code == 400
        assert visites == [], "aucune requête ne doit partir vers une adresse non déclarée"

    def test_l_adresse_refusee_n_est_pas_reecrite_dans_la_reponse(self, client: TestClient) -> None:
        """Reprendre l'adresse reçue laisserait un tiers s'exprimer par notre service."""
        reponse = _lancer(client, iss="https://serveur-de-l-attaquant.test/fhir", launch="x")
        assert "attaquant" not in reponse.text

    def test_une_adresse_declaree_ouvre_le_parcours(
        self, client: TestClient, visites: list[str]
    ) -> None:
        reponse = _lancer(client, iss=SECURISE.base, launch=LANCEMENT)
        assert reponse.status_code == 302
        assert visites == [SECURISE.base]

    def test_la_barre_oblique_finale_ne_change_rien(self, client: TestClient) -> None:
        """Un dossier peut annoncer sa base avec ou sans barre finale."""
        assert _lancer(client, iss=f"{SECURISE.base}/", launch=LANCEMENT).status_code == 302


class TestContexteDeLancement:
    """Le jeton de lancement porte le patient : sans lui, le parcours n'a pas d'objet."""

    def test_un_lancement_sans_contexte_est_refuse(self, client: TestClient) -> None:
        assert _lancer(client, iss=SECURISE.base).status_code == 400

    def test_le_jeton_est_transmis_au_serveur_d_autorisation(self, client: TestClient) -> None:
        demande = _demande(_lancer(client, iss=SECURISE.base, launch=LANCEMENT))
        assert demande["launch"] == [LANCEMENT]

    def test_la_session_retient_la_base_du_serveur_reconnu(self, client: TestClient) -> None:
        """Le retour et les consultations la relisent : une base perdue lirait ailleurs."""
        reponse = _lancer(client, iss=SECURISE.base, launch=LANCEMENT)
        temoin = reponse.cookies[module.TEMOIN]
        session = module.sessions.lire(temoin)
        assert session is not None
        assert session.base == SECURISE.base


class TestScopesSelonLeMode:
    """Les deux modes demandent une portée de contexte différente."""

    def test_le_lancement_depuis_un_dossier_demande_launch(self, client: TestClient) -> None:
        portees = _demande(_lancer(client, iss=SECURISE.base, launch=LANCEMENT))["scope"][0]
        assert "launch" in portees.split()
        assert "launch/patient" not in portees.split()

    def test_le_lancement_depuis_un_dossier_ignore_les_portees_declarees(
        self, client: TestClient
    ) -> None:
        """Le dossier fournit le contexte : `patient/` y désigne quelqu'un, `user/` l'oublierait."""
        portees = _demande(_lancer(client, iss=SECURISE.base, launch=LANCEMENT))["scope"][0]
        assert "patient/Patient.read" in portees.split()
        assert not any(portee.startswith("user/") for portee in portees.split())

    def test_le_lancement_autonome_reste_inchange(self, client: TestClient) -> None:
        """Non-régression : la route existante ne demande ni `launch` ni son paramètre."""
        reponse = client.get(
            "/smart/lancer", params={"serveur": LANCEUR.identifiant}, follow_redirects=False
        )
        demande = _demande(reponse)
        assert "launch/patient" in demande["scope"][0].split()
        assert "launch" not in demande


class TestPorteesDeclareesParServeur:
    """Un serveur qui ne désigne pas de patient ne peut pas se voir demander `patient/`."""

    def _portees(self, client: TestClient, serveur: str) -> list[str]:
        reponse = client.get("/smart/lancer", params={"serveur": serveur}, follow_redirects=False)
        return _demande(reponse)["scope"][0].split()

    def test_le_bac_securise_demande_les_portees_de_l_utilisateur(self, client: TestClient) -> None:
        """Mesuré : sans sélecteur de patient, `patient/` s'y fait refuser par `missing-patient`."""
        portees = self._portees(client, SECURISE.identifiant)
        assert "user/Patient.read" in portees
        assert "user/Condition.read" in portees
        assert not any(portee.startswith("patient/") for portee in portees)
        assert "launch/patient" not in portees

    def test_le_lanceur_garde_les_siennes(self, client: TestClient) -> None:
        """Lui désigne le patient : c'est le parcours qui marche, et il ne bouge pas."""
        portees = self._portees(client, LANCEUR.identifiant)
        assert "launch/patient" in portees
        assert "patient/Patient.read" in portees

    def test_chaque_serveur_obtient_les_siennes(self, client: TestClient) -> None:
        """La déclaration est par serveur : deux parcours successifs ne se contaminent pas."""
        assert self._portees(client, LANCEUR.identifiant) != self._portees(
            client, SECURISE.identifiant
        )
