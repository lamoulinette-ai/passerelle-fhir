"""Où va le relevé d'une sonde, et ce qui le rendait perdable.

La propriété qui prime : **un caractère absent de `cp1252` traverse l'écriture.** Un relevé
obtenu par des dizaines d'appels réseau ne doit pas être perdu par la page de codes du
terminal qui l'affiche.

La seconde : les quatre sondes déclarent leurs options depuis un seul endroit. Trois d'entre
elles avaient perdu `--sortie` parce qu'elle n'existait qu'à un seul.
"""

from __future__ import annotations

import argparse
import pkgutil
from pathlib import Path

import pytest

from passerelle import sondes
from passerelle.sondes import sortie

#: Ce que toute sonde doit appeler pour que son relevé survive à la console.
APPELS = ("sortie.declarer(analyseur)", "sortie.delier_de_la_console()", "sortie.publier(")

#: Trois caractères réellement absents de `cp1252` — vérifié, et non supposé. Les guillemets
#: courbes et les points de suspension, qu'on croirait du même lot, y sont représentables :
#: c'est pourquoi le défaut n'était pas apparu plus tôt.
#:
#: `U+2012` est celui qui a fait lever la sonde du périmètre, sur un passage de la HAS.
#: Écrits en échappement pour rester visibles dans la source.
HORS_CP1252 = "tiret \u2012, espace fine \u202f, espace \u2009 etroite."


class TestEcriture:
    def test_un_caractere_hors_cp1252_traverse_l_ecriture(self, tmp_path: Path) -> None:
        chemin = tmp_path / "releve.md"
        sortie.publier(HORS_CP1252, chemin)
        assert chemin.read_text(encoding="utf-8") == HORS_CP1252

    def test_l_encodage_est_utf8_quel_que_soit_l_hote(self, tmp_path: Path) -> None:
        """Lu en `cp1252`, le fichier serait illisible : c'est ce qui prouve l'encodage."""
        chemin = tmp_path / "releve.md"
        sortie.publier("caractère ‒", chemin)
        assert chemin.read_bytes().decode("utf-8") == "caractère ‒"

    def test_le_dossier_manquant_est_cree(self, tmp_path: Path) -> None:
        """`docs/` n'existe pas dans une copie fraîche du dépôt."""
        chemin = tmp_path / "docs" / "releve.md"
        sortie.publier("x", chemin)
        assert chemin.is_file()

    def test_le_nom_du_fichier_part_sur_la_sortie_d_erreur(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """La sortie standard doit rester redirigeable sans message de service."""
        sortie.publier("contenu", tmp_path / "releve.md")
        capture = capsys.readouterr()
        assert capture.out == ""
        assert "releve.md" in capture.err


class TestAffichage:
    def test_sans_chemin_le_rendu_part_sur_la_sortie_standard(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sortie.publier("le relevé")
        assert capsys.readouterr().out == "le relevé\n"

    def test_delier_ne_leve_pas_sur_des_flux_detournes(self) -> None:
        """Sous capture de pytest, `reconfigure` n'existe pas — l'appel doit rester sans effet."""
        sortie.delier_de_la_console()


class TestOptions:
    def test_les_deux_options_sont_posees(self) -> None:
        analyseur = argparse.ArgumentParser()
        sortie.declarer(analyseur)
        arguments = analyseur.parse_args([])
        assert arguments.json is False
        assert arguments.sortie is None

    def test_sortie_est_lue_comme_un_chemin(self) -> None:
        analyseur = argparse.ArgumentParser()
        sortie.declarer(analyseur)
        arguments = analyseur.parse_args(["--sortie", "docs/releve.md", "--json"])
        assert arguments.sortie == Path("docs/releve.md")
        assert arguments.json is True


class TestSondes:
    def test_toute_sonde_declare_sa_sortie(self) -> None:
        """La régression que ce lot corrige : trois sondes sur quatre n'avaient pas `--sortie`.

        Les modules sont découverts, non énumérés : une cinquième sonde qui oublierait
        `sortie.declarer` échouerait ici sans que personne ait pensé à l'ajouter au test.
        """
        vues: list[str] = []
        for information in pkgutil.iter_modules(sondes.__path__):
            source = (Path(sondes.__path__[0]) / f"{information.name}.py").read_text(
                encoding="utf-8"
            )
            if "def main() -> int:" not in source:
                continue
            vues.append(information.name)
            for appel in APPELS:
                assert appel in source, f"{information.name} : {appel} manquant"
        # Le seuil ne compte pas les sondes, il prouve que la découverte en a trouvé : une
        # boucle qui ne parcourt rien passerait sinon sans rien vérifier. Le figer à un
        # nombre exact obligerait à modifier ce test pour ajouter une sonde, ce que la
        # docstring promet précisément d'éviter.
        assert len(vues) >= 4, f"sondes trouvées : {vues}"
