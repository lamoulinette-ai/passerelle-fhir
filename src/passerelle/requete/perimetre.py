"""Les pathologies du périmètre, les guides dont elles tiennent leur champ, et les codes.

Ce fichier est de la donnée, pas de la logique : les gabarits le lisent sans le connaître,
et une expansion de `ValueSet` obtenue du Serveur Multi-Terminologies pourra remplacer ces
listes sans qu'aucun gabarit ne change.

**Chaque code porte son fondement, et aucun ne peut être vide** — un test l'exige. La liste
a d'abord été écrite sur la foi des libellés anglais rendus par le serveur FHIR, ce qui
revenait à poser des jugements cliniques sans source et à les présenter comme un périmètre
déclaré. Le fondement est ce qui distingue les deux.

Les guides de parcours de la Haute Autorité de Santé énoncent eux-mêmes ce qu'ils couvrent :
c'est cette phrase, citée, qui fixe le champ. Elle raisonne en stades de sévérité et en
formes cliniques, jamais en codes ; le passage de l'une aux autres reste un pas, et le
fondement dit lequel a été franchi.

Un code générique peut figurer alors qu'aucune donnée observée ne l'emploie : un autre
serveur l'emploiera.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SYSTEME_SNOMED = "http://snomed.info/sct"

#: Codes rencontrés dans les données observées et délibérément hors périmètre, avec le
#: motif de leur exclusion. Consignés pour qu'une absence ne passe pas pour un oubli.
#:
#: Les deux codes de la BPCO n'y sont pas par intuition : le corpus de la HAS a été
#: interrogé sur chacun, et aucun passage ne les rattache à la maladie. Le relevé est dans
#: `docs/perimetre.md`.
ECARTES: dict[str, str] = {
    "15777000": (
        "prédiabète — le guide 2025 lui consacre un chapitre de prévention, mais un "
        "prédiabétique n'a pas de diabète de type 2, et c'est du diabète de type 2 que la "
        "question est posée"
    ),
    "185086009": (
        "bronchite chronique obstructive — interrogé au corpus : aucun passage ne la "
        "rattache à la BPCO. Les indicateurs de qualité la donnent comme motif d'aller "
        "chercher une BPCO, ce qui suppose qu'elle n'en est pas une"
    ),
    "87433001": (
        "emphysème pulmonaire — interrogé au corpus : la BPCO y est dite « souvent "
        "associée » à l'emphysème, qui est aussi une lésion à rechercher au scanner chez "
        "un patient déjà atteint. Une association n'est pas une appartenance"
    ),
}


class Guide(BaseModel):
    """Le guide de parcours dont une pathologie tient son champ.

    `champ` est la phrase par laquelle le guide déclare lui-même ce qu'il couvre, reprise
    telle quelle. La reformuler reviendrait à réintroduire un jugement là où la citation
    suffit.
    """

    titre: str
    date: str
    url: str
    champ: str


class Code(BaseModel):
    """Un code SNOMED du périmètre, et ce qui l'y fait entrer.

    Le libellé du concept ne figure pas ici : la licence d'affiliation SNOMED CT réserve la
    diffusion du contenu terminologique aux utilisateurs autorisés. Un commentaire en regard
    de la déclaration rend le fichier lisible sans constituer une table de correspondance.
    """

    code: str
    #: Ce qui rattache le code à la pathologie : le champ du guide, ou la définition du
    #: concept SNOMED. **Jamais vide.**
    fondement: str


class Pathologie(BaseModel):
    """Une pathologie du périmètre, son guide, et les codes qui la désignent.

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
    guide: Guide
    #: Les codes qui désignent la pathologie, chacun avec son fondement.
    codes: tuple[Code, ...] = Field(default_factory=tuple)
    systeme: str = SYSTEME_SNOMED

    @property
    def identifiants(self) -> set[str]:
        """Les identifiants de tous les codes déclarés."""
        return {declare.code for declare in self.codes}

    def apparie(self, systeme: str, code: str) -> bool:
        """Vrai si un code appartient à cette pathologie."""
        return systeme == self.systeme and code in self.identifiants


DIABETE = Guide(
    titre="Parcours de soins du patient adulte vivant avec un diabète de type 2",
    date="juillet 2025",
    url="https://www.has-sante.fr/jcms/p_3634754/",
    champ=(
        "les soins, l'accompagnement et le suivi global de l'adulte vivant avec un diabète "
        "de type 2"
    ),
)

INSUFFISANCE_CARDIAQUE = Guide(
    titre="Guide du parcours de soins « Insuffisance cardiaque »",
    date="février 2012, actualisé juin 2014",
    url="https://www.has-sante.fr/jcms/c_1242988/",
    champ="le parcours de soins d'une personne ayant une insuffisance cardiaque (IC) chronique",
)

BPCO = Guide(
    titre="Guide du parcours de soins « Bronchopneumopathie chronique obstructive »",
    date="actualisation 2019",
    url="https://www.has-sante.fr/jcms/c_1242507/",
    champ="toutes les formes de la BPCO, des stades léger et modéré au stade sévère",
)


PATHOLOGIES: tuple[Pathologie, ...] = (
    Pathologie(
        identifiant="diabete",
        libelle="diabète de type 2",
        article="du ",
        defini="le ",
        guide=DIABETE,
        codes=(
            Code(  # Diabetes mellitus type 2
                code="44054006",
                fondement="le champ du guide, exactement : le diabète de type 2 de l'adulte",
            ),
            Code(  # Neuropathy due to type 2 diabetes mellitus
                code="368581000119106",
                fondement=(
                    "le concept est défini par « due to type 2 diabetes mellitus » : sa "
                    "présence entraîne le diabète de type 2, et le guide range les "
                    "neuropathies parmi les complications à dépister chez ce patient"
                ),
            ),
        ),
    ),
    Pathologie(
        identifiant="insuffisance_cardiaque",
        libelle="insuffisance cardiaque",
        article="de l'",
        defini="l'",
        guide=INSUFFISANCE_CARDIAQUE,
        codes=(
            Code(  # Heart failure
                code="84114007",
                fondement=(
                    "le champ du guide, débordé : le concept couvre aussi l'insuffisance "
                    "cardiaque aiguë, que le guide ne traite pas"
                ),
            ),
            Code(  # Chronic congestive heart failure
                code="88805009",
                fondement="le champ du guide, qui porte sur l'insuffisance cardiaque chronique",
            ),
        ),
    ),
    Pathologie(
        identifiant="bpco",
        libelle="bronchopneumopathie chronique obstructive",
        article="de la ",
        defini="la ",
        guide=BPCO,
        codes=(
            Code(  # Chronic obstructive lung disease
                code="13645005",
                fondement="le champ du guide : toutes les formes de la BPCO",
            ),
        ),
    ),
)


def pathologie(systeme: str, code: str) -> Pathologie | None:
    """Rend la pathologie que désigne un code, ou `None` s'il est hors périmètre."""
    return next((p for p in PATHOLOGIES if p.apparie(systeme, code)), None)
