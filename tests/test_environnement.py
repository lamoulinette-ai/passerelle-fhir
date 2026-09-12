"""Ce que le chargement de la configuration doit tenir.

Trois propriétés, dont deux se voient rarement à l'usage :

- **l'environnement déjà posé garde la main** — un conteneur reçoit ses variables par son
  orchestrateur, et un fichier oublié dans l'image ne doit pas les remplacer ;
- **importer une sonde charge le fichier**, au même titre que démarrer le service : les
  points d'entrée sont distincts, la configuration est la même ;
- **le repli de l'identifiant de client s'annonce**, faute de quoi il se lit dans le message
  d'erreur d'un tiers, qui ne nomme pas la variable manquante.
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path

import pytest

import passerelle.sondes
from passerelle import environnement
from passerelle.smart import autorisation


@pytest.fixture(autouse=True)
def environnement_isole(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une copie, pour que les écritures des tests ne débordent pas sur les suivants."""
    monkeypatch.setattr(os, "environ", dict(os.environ))


class TestChargement:
    def test_une_variable_du_fichier_est_posee(self, tmp_path: Path) -> None:
        fichier = tmp_path / ".env"
        fichier.write_text("PASSERELLE_ESSAI=valeur\n", encoding="utf-8")
        os.environ.pop("PASSERELLE_ESSAI", None)
        environnement.charger(fichier)
        assert os.environ["PASSERELLE_ESSAI"] == "valeur"

    def test_une_variable_deja_posee_n_est_pas_ecrasee(self, tmp_path: Path) -> None:
        fichier = tmp_path / ".env"
        fichier.write_text("PASSERELLE_ESSAI=du_fichier\n", encoding="utf-8")
        os.environ["PASSERELLE_ESSAI"] = "de_l_orchestrateur"
        environnement.charger(fichier)
        assert os.environ["PASSERELLE_ESSAI"] == "de_l_orchestrateur"

    def test_commentaires_lignes_vides_et_lignes_sans_egal_sont_ignores(
        self, tmp_path: Path
    ) -> None:
        fichier = tmp_path / ".env"
        fichier.write_text(
            "# un commentaire\n\nligne sans egal\nPASSERELLE_ESSAI=v # en fin de ligne\n",
            encoding="utf-8",
        )
        os.environ.pop("PASSERELLE_ESSAI", None)
        environnement.charger(fichier)
        assert os.environ["PASSERELLE_ESSAI"] == "v"

    def test_un_fichier_absent_ne_leve_rien(self, tmp_path: Path) -> None:
        environnement.charger(tmp_path / "inexistant")


class TestPointsDEntree:
    def test_importer_les_sondes_charge_le_fichier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Une sonde n'importe pas le service HTTP : elle doit lire la configuration seule."""
        (tmp_path / ".env").write_text("PASSERELLE_ESSAI_SONDE=lu\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        os.environ.pop("PASSERELLE_ESSAI_SONDE", None)
        importlib.reload(passerelle.sondes)
        assert os.environ["PASSERELLE_ESSAI_SONDE"] == "lu"


class TestIdentifiantDeClient:
    def test_la_valeur_declaree_est_rendue(self) -> None:
        os.environ["PASSERELLE_SMART_CLIENT_ID"] = "  un-identifiant  "
        assert autorisation.client_id() == "un-identifiant"

    def test_le_repli_est_signale(self, caplog: pytest.LogCaptureFixture) -> None:
        os.environ.pop("PASSERELLE_SMART_CLIENT_ID", None)
        with caplog.at_level(logging.WARNING, logger="passerelle.smart"):
            assert autorisation.client_id() == autorisation.CLIENT_DEFAUT
        assert "PASSERELLE_SMART_CLIENT_ID" in caplog.text
