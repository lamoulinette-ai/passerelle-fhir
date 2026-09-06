"""Formulation de la question documentaire.

Aucun modèle de langage n'intervient. Le gabarit **est** la spécification : il se lit, se
teste et se journalise intégralement, et il ne décide jamais de ce qui est cliniquement
pertinent.

Deux familles de formulations coexistent, et la différence entre elles est un fait de langue
plutôt qu'un choix d'architecture. Les cinq formes **mesurées** s'adressent aux pathologies
du périmètre, dont l'article est écrit à la main, pathologie par pathologie ; la **forme
libre** s'adresse à une condition quelconque, dont aucune heuristique ne déduit le genre.

Le périmètre ne filtre plus rien : il distingue les questions préparées des autres. La sonde
`sonde-formulations` rejoue la comparaison des cinq premières, `sonde-libre` mesure ce que la
sixième obtient.
"""

from __future__ import annotations

from enum import StrEnum

from passerelle.fhir.schemas import ContextePatient, Probleme
from passerelle.requete.perimetre import Pathologie, pathologie


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

#: Formulation pour une condition que l'utilisateur désigne lui-même.
#:
#: Les cinq formulations ci-dessus supposent un article — « du diabète », « de l'insuffisance
#: cardiaque » — qui est de la donnée, écrite pathologie par pathologie, parce qu'aucune
#: heuristique ne déduit le genre d'un mot français. Un libellé quelconque n'en a pas.
#:
#: Le deux-points contourne le problème au lieu de le deviner : il introduit le libellé sans
#: rien accorder. Ce que cette forme obtient du corpus est une question ouverte, que
#: `sonde-libre` mesure — elle n'a pas été éprouvée quand les cinq autres l'ont été.
FORMULATION_LIBRE = "que publie la Haute Autorité de Santé sur : {libelle} ?"


def question_libre(libelle: str) -> str:
    """Rend la question posée pour une condition désignée par l'utilisateur."""
    return FORMULATION_LIBRE.format(libelle=libelle.strip())


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
