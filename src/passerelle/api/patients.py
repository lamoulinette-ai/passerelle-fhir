"""Les patients de la démonstration, déclarés serveur par serveur.

Choisis dans les bacs à sable sur deux critères : **vivants** — le premier patient relevé au
bloc 1 était mort en 1969 — et de longueurs différentes, du dossier fourni au dossier court.

Un identifiant ne vaut que sur le serveur qui le publie : ceux du lanceur SMART n'existent
pas chez Oracle, et réciproquement. C'est `serveurs` qui porte cette appartenance, et c'est
elle qui borne ce qu'une consultation s'autorise à lire.

Les décomptes sont repris de relevés de sonde, jamais écrits de mémoire : rédigés à la main,
ils ont continué d'annoncer des pathologies que le périmètre ne retenait plus. Un écart entre
ce fichier et `docs/terminologie_releve.md` ou `docs/oracle_releve.md` est un libellé à
corriger, pas une mesure à réinterpréter.
"""

from __future__ import annotations

from pydantic import BaseModel


class PatientDemonstration(BaseModel):
    """Un patient d'un bac à sable, et l'ampleur de son dossier.

    `illustre` décrit ce qui a été **lu**, jamais ce qui mériterait une question : toutes les
    conditions d'un dossier sont interrogeables, et en annoncer un sous-ensemble reviendrait
    à trier pour l'utilisateur.
    """

    identifiant: str
    libelle: str
    illustre: str
    #: Identifiants des serveurs déclarés où ce dossier existe. Jamais vide.
    serveurs: tuple[str, ...]


#: Les deux bacs à sable d'Oracle partagent leur tenant : les mêmes identifiants s'y lisent.
_ORACLE = ("oracle_ouvert", "oracle_securise")

PATIENTS: tuple[PatientDemonstration, ...] = (
    PatientDemonstration(
        identifiant="bd6f9f37-7295-4cd6-b212-134afcef1253",
        libelle="Homme, né en 1956",
        illustre="vingt-deux conditions lues — le dossier le plus fourni",
        serveurs=("lanceur",),
    ),
    PatientDemonstration(
        identifiant="ebb1f0e2-4fa6-4889-a43b-9cda3c737078",
        libelle="Femme, née en 1988",
        illustre="quinze conditions lues",
        serveurs=("lanceur",),
    ),
    PatientDemonstration(
        identifiant="7217c081-64cf-4e6c-b023-05c2e2dcf50c",
        libelle="Femme, née en 1953",
        illustre="quatorze conditions lues",
        serveurs=("lanceur",),
    ),
    PatientDemonstration(
        identifiant="beaf0c3d-bcd4-4155-8a7b-f493bdc8f9fe",
        libelle="Femme, née en 1953 (dossier court)",
        illustre="sept conditions lues — le dossier le plus court",
        serveurs=("lanceur",),
    ),
    # Les trois dossiers Oracle. Aucun décompte dans le libellé : il diffère d'un bac à sable
    # à l'autre pour le même identifiant, et la page l'affiche de toute façon après lecture.
    PatientDemonstration(
        identifiant="12743119",
        libelle="Homme, 80 ans",
        illustre="dossier volumineux",
        serveurs=_ORACLE,
    ),
    PatientDemonstration(
        identifiant="12746484",
        libelle="Femme, 69 ans",
        illustre="dossier volumineux",
        serveurs=_ORACLE,
    ),
    PatientDemonstration(
        identifiant="12742497",
        libelle="Femme, 54 ans",
        illustre="dossier court",
        serveurs=_ORACLE,
    ),
)


def patients_de(serveur: str) -> tuple[PatientDemonstration, ...]:
    """Les dossiers déclarés d'un serveur, vides si aucun ne l'est."""
    return tuple(patient for patient in PATIENTS if serveur in patient.serveurs)


def est_declare(identifiant: str, serveur: str) -> bool:
    """Vrai si ce dossier est déclaré sur ce serveur.

    C'est le plancher de tous les contrôles d'accès de la passerelle : quelle que soit
    l'autorisation obtenue, un dossier absent d'ici n'est jamais lu.
    """
    return any(patient.identifiant == identifiant for patient in patients_de(serveur))
