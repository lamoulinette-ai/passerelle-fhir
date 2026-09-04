"""Ce que rend l'API du documentaliste, repris fidèlement.

Rien n'est réinterprété : l'issue, les défauts et l'indisponibilité de rédaction sont des
décisions déjà prises en amont, mesurées là-bas. Les recalculer ici produirait un second
avis qui contredirait le premier sans rien mesurer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Passage(BaseModel):
    """Un passage du corpus et de quoi le retrouver dans la publication d'origine."""

    numero: int
    document: str
    page: int
    texte: str
    titre: str = ""
    url: str = ""
    type_publication: str = ""
    mise_en_ligne: str = ""


class Affirmation(BaseModel):
    """Une phrase et le passage qui doit l'établir."""

    texte: str
    extrait: int


class Defaut(BaseModel):
    """Ce qu'une affirmation a de vérifiablement faux, contrôlé sans modèle."""

    affirmation: str
    motif: str
    piece: str = ""


class Reponse(BaseModel):
    """La réponse du documentaliste à une question."""

    question: str
    #: « reponse », « constat_absence » ou « refus ».
    issue: str
    refus: str = ""
    affirmations: list[Affirmation] = Field(default_factory=list)
    #: Toujours renseigné, refus compris.
    passages: list[Passage] = Field(default_factory=list)
    defauts: list[Defaut] = Field(default_factory=list)
    redaction_indisponible: bool = False

    #: Renseigné quand la réponse vient des exemples enregistrés et non du service.
    #: Absent de la charge rendue par l'API : c'est la passerelle qui le pose.
    origine: str = "service"

    @property
    def enregistree(self) -> bool:
        """Vrai si la réponse vient des exemples et non d'un appel."""
        return self.origine != "service"
