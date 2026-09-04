"""Modèle interne du contexte patient.

Ce modèle n'est pas une ressource FHIR : il ne retient d'un dossier que ce qu'une requête
documentaire peut employer. Nom, adresse, téléphone, numéro de sécurité sociale, permis de
conduire et passeport sont présents dans les ressources lues et n'ont pas de représentation
ici.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

SYSTEME_SNOMED = "http://snomed.info/sct"


class CodeClinique(BaseModel):
    """Un code terminologique et ses deux libellés : celui de la source, celui du SMT."""

    systeme: str
    code: str
    libelle_source: str = ""
    libelle_fr: str | None = None

    @property
    def resolu(self) -> bool:
        """Vrai si le code a reçu un libellé français."""
        return bool(self.libelle_fr)


class Probleme(BaseModel):
    """Une ressource `Condition` réduite à son code, son statut et sa date de début."""

    code: CodeClinique
    statut: str = ""
    debut: date | None = None

    @property
    def actif(self) -> bool:
        """Vrai si le statut clinique vaut `active`."""
        return self.statut == "active"


class ContextePatient(BaseModel):
    """Ce que la passerelle retient d'un dossier, et rien de plus."""

    identifiant: str
    sexe: str | None = None
    naissance: date | None = None
    deces: date | None = None
    problemes: list[Probleme] = Field(default_factory=list)

    @property
    def vivant(self) -> bool:
        """Vrai en l'absence de date de décès."""
        return self.deces is None

    def age(self, reference: date | None = None) -> int | None:
        """Âge en années révolues à la date de référence, ou à la date de décès."""
        if self.naissance is None:
            return None
        borne = reference or self.deces or date.today()
        ecart = borne.year - self.naissance.year
        if (borne.month, borne.day) < (self.naissance.month, self.naissance.day):
            ecart -= 1
        return ecart

    @property
    def actifs(self) -> list[Probleme]:
        """Les problèmes dont le statut clinique est actif."""
        return [probleme for probleme in self.problemes if probleme.actif]
