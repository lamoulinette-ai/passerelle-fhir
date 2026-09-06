"""Où va le relevé d'une sonde, et dans quel encodage.

Les quatre sondes rendent du texte français dont une part vient de corpus qu'elles ne
contrôlent pas — publications de la HAS, libellés de terminologies. La console Windows,
en `cp1252`, ne sait pas écrire tout ce que ce texte contient : un tiret numéral suffit à
faire lever l'encodage **après** que la mesure a été faite, ce qui perd un relevé obtenu.

Deux réponses, et il faut les deux. Écrire dans un fichier au lieu de la console met le
relevé hors d'atteinte de la page de codes. Délier la sortie standard de la console couvre
le cas où l'appelant n'a pas demandé de fichier.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def delier_de_la_console() -> None:
    """Passe les sorties en UTF-8 quand la console impose une page de codes étroite.

    Appelée en tête de `main()`, avant tout affichage. Les flux détournés par un cadre de
    test n'exposent pas `reconfigure` : leur encodage est déjà celui du cadre.
    """
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8")


def declarer(analyseur: argparse.ArgumentParser) -> None:
    """Pose `--json` et `--sortie` sur l'analyseur d'une sonde.

    Déclarées ici plutôt que dans chaque sonde : quatre copies d'une même option finissent
    par diverger, et c'est en divergeant qu'une seule d'entre elles avait reçu `--sortie`.
    """
    analyseur.add_argument("--json", action="store_true", help="rendre le relevé en JSON")
    analyseur.add_argument(
        "--sortie",
        type=Path,
        help="écrit le relevé dans ce fichier, en UTF-8, sans passer par la console",
    )


def publier(rendu: str, chemin: Path | None = None) -> None:
    """Écrit le relevé dans un fichier, ou l'imprime à défaut de chemin.

    Le nom du fichier écrit part sur la sortie d'erreur : la sortie standard doit rester
    redirigeable sans qu'un message de service s'y mêle.
    """
    if chemin is None:
        print(rendu)
        return
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(rendu, encoding="utf-8")
    print(f"relevé écrit : {chemin}", file=sys.stderr)
