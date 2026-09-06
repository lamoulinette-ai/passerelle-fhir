"""Les patients de la démonstration, déclarés.

Choisis dans le bac à sable sur trois critères : porteurs des pathologies du périmètre,
**vivants** — le premier patient relevé au bloc 1 était mort en 1969 — et couvrant les cas
que la démonstration doit montrer, y compris celui où il n'y a rien à demander.

Les descriptions sont reprises d'un relevé de `sonde-terminologie`, jamais écrites de
mémoire : rédigées à la main, elles ont continué d'annoncer des pathologies que le périmètre
ne retenait plus. Un écart entre ce fichier et `docs/terminologie_releve.md` est un libellé
à corriger, pas une mesure à réinterpréter.
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
        illustre="vingt-deux conditions lues, une seule retenue — diabète",
    ),
    PatientDemonstration(
        identifiant="ebb1f0e2-4fa6-4889-a43b-9cda3c737078",
        libelle="Femme, née en 1988",
        illustre="quinze conditions lues, une seule retenue — diabète",
    ),
    PatientDemonstration(
        identifiant="7217c081-64cf-4e6c-b023-05c2e2dcf50c",
        libelle="Femme, née en 1953",
        illustre="quatorze conditions lues, une seule retenue — insuffisance cardiaque",
    ),
    PatientDemonstration(
        identifiant="beaf0c3d-bcd4-4155-8a7b-f493bdc8f9fe",
        libelle="Femme, née en 1953 (dossier court)",
        illustre="sept conditions lues, une seule retenue — insuffisance cardiaque",
    ),
    PatientDemonstration(
        identifiant="8364ff74-d904-442b-b984-f9d640531639",
        libelle="Femme, née en 1964",
        illustre="sept conditions lues, aucune du périmètre — aucune question posée",
    ),
)

#: Index par identifiant, pour refuser en une comparaison un patient hors démonstration.
PAR_IDENTIFIANT = {patient.identifiant: patient for patient in PATIENTS}
