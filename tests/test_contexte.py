"""Ce que la passerelle retient d'un dossier, et ce qu'elle refuse d'en retenir.

Deux propriétés valent tous les autres tests de ce fichier :

- **le contexte ne porte aucune donnée d'identification** — les ressources lues contiennent
  nom, adresse, téléphone, numéro de sécurité sociale et passeport, et rien de tout cela
  n'a de représentation dans le modèle interne ;
- **l'extraction ne sélectionne pas** — les conditions résolues et hors périmètre sont
  converties comme les autres, le choix de ce qui compte étant un pas distinct et déclaré.

La première est celle qui se casserait en silence : un champ ajouté au modèle pour un
besoin d'affichage y ferait entrer des données personnelles sans qu'aucun test n'échoue.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from passerelle.fhir.contexte import contexte
from passerelle.fhir.schemas import SYSTEME_SNOMED

EXEMPLES = Path(__file__).parent / "exemples"


@pytest.fixture
def patient() -> dict:
    return json.loads((EXEMPLES / "patient.json").read_text(encoding="utf-8"))


@pytest.fixture
def conditions() -> list[dict]:
    return json.loads((EXEMPLES / "conditions.json").read_text(encoding="utf-8"))


class TestMinimisation:
    """Le modèle interne n'a pas de place où loger une donnée d'identification."""

    def test_le_contexte_ne_porte_pas_d_identite(self, patient, conditions) -> None:
        rendu = contexte(patient, conditions).model_dump_json()
        for interdit in ("Stanton", "Stewart", "999-78-9632", "X84207296X", "555-164-7754"):
            assert interdit not in rendu

    def test_le_contexte_ne_porte_pas_d_adresse(self, patient, conditions) -> None:
        rendu = contexte(patient, conditions).model_dump_json()
        assert "Schowalter" not in rendu and "01089" not in rendu


class TestExtraction:
    def test_l_identifiant_est_repris(self, patient, conditions) -> None:
        assert contexte(patient, conditions).identifiant.startswith("ecaea95c")

    def test_les_dates_sont_lues(self, patient, conditions) -> None:
        rendu = contexte(patient, conditions)
        assert rendu.naissance == date(1915, 7, 3)
        assert rendu.deces == date(1969, 8, 26)

    def test_l_age_se_calcule_au_deces(self, patient, conditions) -> None:
        """Faute de borne, l'âge se compterait jusqu'à aujourd'hui pour un patient de 1915."""
        assert contexte(patient, conditions).age() == 54
        assert not contexte(patient, conditions).vivant

    def test_un_patient_sans_naissance_n_a_pas_d_age(self) -> None:
        assert contexte({"id": "x"}, []).age() is None


class TestProblemes:
    def test_toutes_les_conditions_codees_sont_converties(self, patient, conditions) -> None:
        """Quatre codées sur cinq : la cinquième n'a qu'un texte libre."""
        assert len(contexte(patient, conditions).problemes) == 4

    def test_une_condition_sans_code_est_ecartee(self, patient, conditions) -> None:
        rendu = contexte(patient, conditions)
        assert all(probleme.code.code for probleme in rendu.problemes)

    def test_les_resolues_sont_extraites_mais_distinguees(self, patient, conditions) -> None:
        """L'extraction est fidèle ; le tri par statut vient après, et il est mécanique."""
        rendu = contexte(patient, conditions)
        assert len(rendu.problemes) == 4
        assert len(rendu.actifs) == 3

    def test_le_systeme_et_le_code_sont_conserves(self, patient, conditions) -> None:
        premier = contexte(patient, conditions).problemes[0]
        assert premier.code.systeme == SYSTEME_SNOMED
        assert premier.code.code == "44054006"

    def test_le_libelle_francais_reste_vide(self, patient, conditions) -> None:
        """Aucun libellé français avant la résolution terminologique."""
        rendu = contexte(patient, conditions)
        assert not any(probleme.code.resolu for probleme in rendu.problemes)

    def test_le_libelle_source_n_est_pas_le_nom_du_concept(self, patient, conditions) -> None:
        """`44054006` se nomme « Diabetes mellitus » ; la source écrit « Diabetes ».

        Le code fait foi, le libellé de la source ne peut pas en tenir lieu.
        """
        premier = contexte(patient, conditions).problemes[0]
        assert premier.code.libelle_source == "Diabetes"

    def test_un_dossier_sans_condition_reste_lisible(self, patient) -> None:
        rendu = contexte(patient, [])
        assert rendu.problemes == [] and rendu.actifs == []
