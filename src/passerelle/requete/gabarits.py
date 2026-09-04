"""Construction de la question documentaire à partir du contexte codé.

Aucun modèle de langage n'intervient. Le gabarit **est** la spécification : il se lit, se
teste et se journalise intégralement, et il ne décide jamais de ce qui est cliniquement
pertinent — il apparie des codes déclarés.

Les formulations sont de la donnée, et plusieurs coexistent. Celle qui sert par défaut se
choisit sur mesure, la sonde `sonde-formulations` rendant l'issue obtenue par chacune.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from passerelle.fhir.schemas import ContextePatient, Probleme
from passerelle.requete.perimetre import PATHOLOGIES, Pathologie, pathologie


class Forme(StrEnum):
    """Les formulations candidates, mesurables l'une contre l'autre."""

    LIBELLE = "libellé nu"
    PRISE_EN_CHARGE = "prise en charge"
    PARCOURS = "parcours de soins"
    SUIVI = "suivi"
    PUBLICATIONS = "publications"


#: Gabarits de formulation. Aucune tournure impérative : le système ne prescrit ni n'oriente.
#:
#: Aucune espace entre un article et `{libelle}` : chaque article porte la sienne quand il
#: en faut une (« du », « la ») et n'en porte pas quand il s'élide (« de l' », « l' »).
#: `{article}` est la forme contractée, `{defini}` l'article défini.
FORMULATIONS: dict[Forme, str] = {
    Forme.LIBELLE: "{libelle}",
    Forme.PRISE_EN_CHARGE: "quelle est la prise en charge recommandée {article}{libelle} ?",
    Forme.PARCOURS: (
        "quel parcours de soins la Haute Autorité de Santé décrit-elle pour {defini}{libelle} ?"
    ),
    Forme.SUIVI: "quel suivi la Haute Autorité de Santé décrit-elle pour {defini}{libelle} ?",
    Forme.PUBLICATIONS: "que publie la Haute Autorité de Santé sur {defini}{libelle} ?",
}

#: Formulation employée à défaut, choisie sur mesure et non sur intuition.
#:
#: Sur les trois pathologies du périmètre, `PARCOURS` obtient une réponse à chaque fois et
#: ramène en tête le guide de parcours de soins de la pathologie. `SUIVI` obtient aussi
#: trois réponses mais dérive vers des documents périphériques ; `PRISE_EN_CHARGE`, écrite
#: en premier, se fait refuser les trois fois.
#:
#: La sonde `sonde-formulations` rejoue la comparaison. Les formulations écartées restent
#: déclarées : les retirer rendrait la mesure irreproductible.
FORME_DEFAUT = Forme.PARCOURS


class Requete(BaseModel):
    """Une question documentaire et ce qui l'a produite."""

    gabarit: str
    forme: Forme
    texte: str
    libelle: str
    codes: list[str]


def texte(patho: Pathologie, forme: Forme) -> str:
    """Rend la question d'une pathologie, sous la forme demandée."""
    return FORMULATIONS[forme].format(
        article=patho.article, defini=patho.defini, libelle=patho.libelle
    )


def apparier(contexte: ContextePatient) -> dict[str, list[Probleme]]:
    """Groupe les problèmes **actifs** du contexte par pathologie du périmètre.

    Les problèmes résolus et ceux hors périmètre n'apparaissent pas : le tri par statut
    clinique est mécanique, et l'appartenance au périmètre est déclarée.
    """
    apparies: dict[str, list[Probleme]] = {}
    for probleme in contexte.actifs:
        patho = pathologie(probleme.code.systeme, probleme.code.code)
        if patho is not None:
            apparies.setdefault(patho.identifiant, []).append(probleme)
    return apparies


def construire(contexte: ContextePatient, forme: Forme = FORME_DEFAUT) -> list[Requete]:
    """Rend une requête par pathologie appariée, dans l'ordre du périmètre.

    Un contexte sans pathologie du périmètre rend une liste vide, jamais une requête vide :
    n'avoir rien à demander n'est pas demander quelque chose de creux.
    """
    apparies = apparier(contexte)
    requetes: list[Requete] = []
    for patho in _pathologies_dans_l_ordre(apparies):
        problemes = apparies[patho.identifiant]
        requetes.append(
            Requete(
                gabarit=patho.identifiant,
                forme=forme,
                texte=texte(patho, forme),
                libelle=patho.libelle,
                codes=sorted(probleme.code.code for probleme in problemes),
            )
        )
    return requetes


def _pathologies_dans_l_ordre(apparies: dict[str, list[Probleme]]) -> list[Pathologie]:
    """Rend les pathologies appariées dans l'ordre du périmètre, non celui du dossier.

    L'ordre des ressources rendues par un serveur FHIR n'est pas garanti ; sans cette
    remise en ordre, deux exécutions sur le même dossier produiraient des traces
    différentes.
    """
    return [p for p in PATHOLOGIES if p.identifiant in apparies]
