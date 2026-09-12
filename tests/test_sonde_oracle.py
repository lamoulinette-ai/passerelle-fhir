"""Ce que la sonde Oracle doit tenir, et ce qui la rend utilisable.

Trois propriétés :

- **les portées demandées traversent toute la chaîne** — de l'option de ligne de commande
  jusqu'à l'adresse d'autorisation. C'est la variable de la mesure : la figer dans le code
  obligerait à modifier le dépôt pour poser une question ;
- **le relevé annonce les portées demandées**, sans quoi il serait impossible de dire à quoi
  se rapporte la réponse du serveur ;
- **le préfixe par défaut est `user/`**, seul à ne pas supposer un patient déjà désigné.

Aucun test ne touche au réseau : le parcours d'autorisation est simulé de bout en bout.
"""

from __future__ import annotations

from typing import Any

import pytest

from passerelle.smart.autorisation import AutorisationRefusee, demander
from passerelle.smart.schemas import ConfigurationSmart, Demande, Jeton
from passerelle.sondes import oracle, parcours

CONFIGURATION = ConfigurationSmart(
    authorization_endpoint="https://serveur.test/authorize",
    token_endpoint="https://serveur.test/token",
    code_challenge_methods_supported=["S256"],
)

PORTEES = "user/Patient.read user/Condition.read"


class FauxClient:
    """Un client de lecture qui n'a rien à lire : la mesure 3 porte ici sur une liste vide."""

    def fermer(self) -> None:
        pass


class TestPorteesDemandees:
    def test_elles_figurent_dans_l_adresse_d_autorisation(self) -> None:
        demande = demander(
            CONFIGURATION, "https://serveur.test/fhir", "https://retour.test", portees=PORTEES
        )
        assert "scope=user%2FPatient.read+user%2FCondition.read" in demande.url

    def test_le_parcours_les_transmet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        vues: dict[str, str] = {}

        def faux_demander(
            _configuration: ConfigurationSmart,
            _base: str,
            _redirection: str,
            _lancement: str | None = None,
            portees: str = "",
        ) -> Demande:
            vues["portees"] = portees
            return Demande(url="https://serveur.test/authorize", etat="e", verificateur="v")

        monkeypatch.setattr(parcours, "decouvrir", lambda base, client=None: CONFIGURATION)
        monkeypatch.setattr(parcours, "demander", faux_demander)

        with pytest.raises(AutorisationRefusee):
            parcours.autoriser(
                "https://serveur.test/fhir",
                portees=PORTEES,
                demander_url=lambda _invite: "https://retour.test/?error=access_denied",
            )
        assert vues["portees"] == PORTEES

    def test_la_sonde_les_transmet_et_les_consigne(self, monkeypatch: pytest.MonkeyPatch) -> None:
        vues: dict[str, str] = {}

        def faux_autoriser(base: str, portees: str = "") -> Jeton:
            vues["base"], vues["portees"] = base, portees
            return Jeton(access_token="j", scope=portees)

        monkeypatch.setattr(oracle, "autoriser", faux_autoriser)
        monkeypatch.setattr(oracle, "ClientFhir", lambda _base, entetes=None: FauxClient())

        releve: dict[str, Any] = oracle.avec_jeton_sans_contexte([], PORTEES)

        assert vues["portees"] == PORTEES
        assert "fhir-ehr-code" in vues["base"], "le parcours vise le bac à sable sécurisé"
        assert releve["portees_demandees"] == PORTEES
        assert releve["lectures"] == []


class TestPorteesParDefaut:
    def test_elles_ne_supposent_aucun_patient_designe(self) -> None:
        """`patient/` désigne le patient du contexte : sans contexte, il n'a rien à désigner."""
        portees = oracle.PORTEES_DEFAUT.split()
        assert not any(portee.startswith("patient/") for portee in portees)
        assert {"user/Patient.read", "user/Condition.read"} <= set(portees)
