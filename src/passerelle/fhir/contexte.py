"""Conversion des ressources FHIR lues vers le modèle interne.

L'extraction est fidèle et non sélective : toutes les `Condition` reçues sont converties,
y compris les résolues et celles hors périmètre. Le choix de ce qui compte est un pas
distinct, déclaré ailleurs sous forme de liste de codes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from passerelle.fhir.schemas import CodeClinique, ContextePatient, Probleme


def contexte(patient: dict[str, Any], conditions: Iterable[dict[str, Any]]) -> ContextePatient:
    """Assemble un `ContextePatient` à partir d'une ressource `Patient` et de ses `Condition`."""
    problemes = [converti for ressource in conditions if (converti := _probleme(ressource))]
    return ContextePatient(
        identifiant=str(patient.get("id", "")),
        sexe=patient.get("gender"),
        naissance=_date(patient.get("birthDate")),
        deces=_date(patient.get("deceasedDateTime")),
        problemes=problemes,
    )


def _probleme(ressource: dict[str, Any]) -> Probleme | None:
    """Convertit une `Condition` ; rend `None` si elle ne porte aucun code exploitable."""
    code = _code(ressource.get("code"))
    if code is None:
        return None
    return Probleme(
        code=code,
        statut=_statut(ressource.get("clinicalStatus")),
        debut=_date(ressource.get("onsetDateTime")),
    )


def _code(concept: dict[str, Any] | None) -> CodeClinique | None:
    """Retient le premier codage d'un `CodeableConcept`."""
    if not concept:
        return None
    codages = concept.get("coding") or []
    for codage in codages:
        systeme, valeur = codage.get("system"), codage.get("code")
        if systeme and valeur:
            return CodeClinique(
                systeme=systeme,
                code=str(valeur),
                libelle_source=codage.get("display") or concept.get("text") or "",
            )
    return None


def _statut(concept: dict[str, Any] | None) -> str:
    """Rend le code du statut clinique, chaîne vide s'il est absent."""
    if not concept:
        return ""
    codages = concept.get("coding") or []
    return str(codages[0].get("code", "")) if codages else ""


def _date(valeur: Any) -> date | None:
    """Lit une date FHIR, `date` comme `dateTime`, en ignorant ce qui suit le jour."""
    if not isinstance(valeur, str) or len(valeur) < 10:
        return None
    try:
        return date.fromisoformat(valeur[:10])
    except ValueError:
        return None
