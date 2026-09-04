"""Les pathologies du périmètre, et les codes qui les désignent.

Ce fichier est de la donnée, pas de la logique : les gabarits le lisent sans le connaître,
et une expansion de `ValueSet` obtenue du Serveur Multi-Terminologies pourra remplacer ces
listes sans qu'aucun gabarit ne change.

Les codes génériques figurent bien qu'aucun ne soit employé par les données observées :
un autre serveur les emploiera.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SYSTEME_SNOMED = "http://snomed.info/sct"

#: Codes présents dans les données observées mais délibérément hors périmètre.
#:
#: Le prédiabète est un concept distinct du diabète. L'apparier au gabarit du diabète
#: reviendrait à décider qu'il relève de la même prise en charge — un jugement clinique,
#: que la conception s'interdit. Consigné ici pour que l'absence ne passe pas pour un oubli.
ECARTES: dict[str, str] = {
    "15777000": "prédiabète — concept distinct du diabète, hors périmètre déclaré",
}


class Pathologie(BaseModel):
    """Une pathologie du périmètre et les codes qui la désignent.

    Les deux articles sont des données et non des règles : le genre grammatical français ne
    se déduit pas de l'orthographe, et une heuristique produirait « du bronchopneumopathie ».

    Chacun porte son espace finale quand il en faut une — « du », « la » — et n'en porte pas
    quand il s'élide — « de l' », « l' ». Retirer cette espace casse la moitié des
    formulations ; en ajouter une en casse l'autre moitié.
    """

    identifiant: str
    libelle: str
    #: Article contracté, pour « la prise en charge ___ » : « du », « de la », « de l' ».
    article: str
    #: Article défini, pour « sur ___ » ou « pour ___ » : « le », « la », « l' ».
    defini: str
    codes: set[str] = Field(default_factory=set)
    systeme: str = SYSTEME_SNOMED

    def apparie(self, systeme: str, code: str) -> bool:
        """Vrai si un code appartient à cette pathologie."""
        return systeme == self.systeme and code in self.codes


PATHOLOGIES: tuple[Pathologie, ...] = (
    Pathologie(
        identifiant="diabete",
        libelle="diabète de type 2",
        article="du ",
        defini="le ",
        codes={
            "44054006",  # Diabetes mellitus type 2
            "368581000119106",  # Neuropathy due to type 2 diabetes mellitus
        },
    ),
    Pathologie(
        identifiant="insuffisance_cardiaque",
        libelle="insuffisance cardiaque",
        article="de l'",
        defini="l'",
        codes={
            "88805009",  # Chronic congestive heart failure
            "84114007",  # Heart failure
        },
    ),
    Pathologie(
        identifiant="bpco",
        libelle="bronchopneumopathie chronique obstructive",
        article="de la ",
        defini="la ",
        codes={
            "185086009",  # Chronic obstructive bronchitis
            "87433001",  # Pulmonary emphysema
            "13645005",  # Chronic obstructive lung disease
        },
    ),
)


def pathologie(systeme: str, code: str) -> Pathologie | None:
    """Rend la pathologie que désigne un code, ou `None` s'il est hors périmètre."""
    return next((p for p in PATHOLOGIES if p.apparie(systeme, code)), None)
