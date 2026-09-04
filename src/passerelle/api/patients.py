"""Les patients de la démonstration, déclarés.

Choisis dans le bac à sable sur trois critères : porteurs des pathologies du périmètre,
**vivants** — le premier patient relevé au bloc 1 était mort en 1969 — et couvrant les cas
que la démonstration doit montrer, y compris celui où il n'y a rien à demander.

Le dernier de la liste est le plus utile : il ne porte aucune pathologie du périmètre. La
passerelle ne construit alors aucune requête, et c'est ce qu'il faut voir.
"""

from __future__ import annotations

from pydantic import BaseModel


class PatientDemonstration(BaseModel):
    """Un patient du bac à sable, et ce qu'il illustre."""

    identifiant: str
    libelle: str
    illustre: str


PATIENTS: tuple[PatientDemonstration, ...] = (
    PatientDemonstration(
        identifiant="bd6f9f37-7295-4cd6-b212-134afcef1253",
        libelle="Homme, né en 1956",
        illustre="deux pathologies du périmètre — BPCO et diabète, donc deux requêtes",
    ),
    PatientDemonstration(
        identifiant="beaf0c3d-bcd4-4155-8a7b-f493bdc8f9fe",
        libelle="Femme, née en 1953",
        illustre="deux pathologies du périmètre — BPCO et insuffisance cardiaque",
    ),
    PatientDemonstration(
        identifiant="ebb1f0e2-4fa6-4889-a43b-9cda3c737078",
        libelle="Femme, née en 1988",
        illustre="une seule pathologie du périmètre — diabète",
    ),
    PatientDemonstration(
        identifiant="7217c081-64cf-4e6c-b023-05c2e2dcf50c",
        libelle="Femme, née en 1953",
        illustre="une seule pathologie du périmètre — insuffisance cardiaque",
    ),
    PatientDemonstration(
        identifiant="8364ff74-d904-442b-b984-f9d640531639",
        libelle="Femme, née en 1964",
        illustre="aucune pathologie du périmètre malgré sept conditions — aucune requête",
    ),
)

#: Index par identifiant, pour refuser en une comparaison un patient hors démonstration.
PAR_IDENTIFIANT = {patient.identifiant: patient for patient in PATIENTS}
