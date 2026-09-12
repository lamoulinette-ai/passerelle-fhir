"""Modèles de l'autorisation SMART on FHIR.

Aucun point d'entrée n'est écrit en dur : `ConfigurationSmart` porte ceux que le serveur
publie, et c'est le seul endroit d'où l'autorisation les tire.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: Scopes demandés faute de `PASSERELLE_SMART_SCOPES`. Syntaxe v1, la plus largement
#: acceptée ; la sonde de conformité dira ce que chaque serveur accepte réellement.
SCOPES_DEFAUT = "launch/patient patient/Patient.read patient/Condition.read openid fhirUser"

#: Scopes du lancement depuis un dossier patient, faute de `PASSERELLE_SMART_SCOPES_EHR`.
#: `launch` remplace `launch/patient` : le contexte vient du jeton de lancement, il n'est
#: pas demandé au serveur d'autorisation.
SCOPES_EHR_DEFAUT = "launch patient/Patient.read patient/Condition.read openid fhirUser"


class ConfigurationSmart(BaseModel):
    """Ce que publie `.well-known/smart-configuration`, réduit à ce qui sert."""

    authorization_endpoint: str
    token_endpoint: str
    issuer: str | None = None
    introspection_endpoint: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    scopes_supported: list[str] = Field(default_factory=list)
    code_challenge_methods_supported: list[str] = Field(default_factory=list)
    grant_types_supported: list[str] = Field(default_factory=list)

    @property
    def pkce_s256(self) -> bool:
        """Vrai si le serveur annonce PKCE avec SHA-256."""
        return "S256" in self.code_challenge_methods_supported

    @property
    def lancement_autonome(self) -> bool:
        """Vrai si le serveur annonce le lancement autonome."""
        return "launch-standalone" in self.capabilities


class Demande(BaseModel):
    """L'état d'un parcours en cours, entre la redirection et le retour.

    Le vérificateur ne sort jamais du serveur : seule son empreinte part chez le serveur
    d'autorisation, et c'est ce qui empêche un tiers d'échanger un code intercepté.
    """

    url: str
    etat: str
    verificateur: str


class Jeton(BaseModel):
    """La réponse du point d'entrée de jeton.

    `patient` porte le contexte de lancement. C'est de lui que la passerelle tire le seul
    dossier qu'elle s'autorise à lire — le serveur, lui, ne l'impose pas toujours.
    """

    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    scope: str = ""
    patient: str | None = None
    id_token: str | None = None
    refresh_token: str | None = None

    @property
    def entete(self) -> dict[str, str]:
        """En-tête d'autorisation à joindre aux requêtes FHIR."""
        return {"Authorization": f"{self.token_type} {self.access_token}"}

    @property
    def scopes(self) -> list[str]:
        """Les scopes réellement accordés, qui peuvent différer des scopes demandés."""
        return self.scope.split()
