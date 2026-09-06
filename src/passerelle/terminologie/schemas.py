"""Ce qu'un concept résolu porte, et rien de plus."""

from __future__ import annotations

from pydantic import BaseModel


class Concept(BaseModel):
    """Un concept résolu et la version du référentiel qui l'atteste.

    `libelle_fr` est renseigné **uniquement** quand le serveur rend une désignation de
    langue française. `display` est rendu dans tous les cas, y compris pour un concept
    jamais traduit : les confondre publierait un taux de correspondance flatteur et faux.
    """

    systeme: str
    code: str
    display: str = ""
    libelle_fr: str | None = None
    version: str = ""
    terminologie: str = ""

    @property
    def resolu(self) -> bool:
        """Vrai quand une désignation française existe."""
        return self.libelle_fr is not None

    @property
    def libelle(self) -> str:
        """Le français s'il existe, le libellé du serveur à défaut."""
        return self.libelle_fr or self.display
