"""Lecture du fichier `.env`.

Le dépôt a plusieurs points d'entrée — le service HTTP et les sept sondes — qui ont besoin
de la même configuration. Elle est donc chargée ici, et non dans l'un d'eux.
"""

from __future__ import annotations

import os
from pathlib import Path


def charger(chemin: Path = Path(".env")) -> None:
    """Charge un fichier `.env` s'il existe, sans écraser l'environnement déjà posé."""
    if not chemin.is_file():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        nue = ligne.strip()
        if not nue or nue.startswith("#") or "=" not in nue:
            continue
        cle, _, valeur = nue.partition("=")
        os.environ.setdefault(cle.strip(), valeur.split("#")[0].strip())
