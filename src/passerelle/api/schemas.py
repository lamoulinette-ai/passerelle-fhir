"""Ce que l'API reçoit et ce qu'elle rend.

Une décision d'interface est inscrite ici plutôt que dans la page : **une consultation rend
toujours son identifiant de trace**, y compris quand elle échoue. Laisser ce choix à la page
reviendrait à pouvoir l'oublier, et une trace qu'on ne peut pas retrouver ne trace rien.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from passerelle.documentaliste.schemas import Affirmation, Defaut, Passage
from passerelle.journal.schemas import Mode


class Consultation(BaseModel):
    """La demande : un patient, et sous quel mode le lire."""

    patient: str = Field(min_length=1, max_length=128)
    mode: Mode = Mode.DEMONSTRATION


class ProblemeRendu(BaseModel):
    """Un problème du dossier, tel qu'il a été lu puis résolu — ou non."""

    systeme: str
    code: str
    libelle_source: str = ""
    libelle_fr: str | None = None
    statut: str = ""
    dans_le_perimetre: bool = False


class RequeteRendue(BaseModel):
    """Une question construite, et ce que le moteur documentaire en a fait."""

    gabarit: str
    texte: str
    codes: list[str] = Field(default_factory=list)
    issue: str = ""
    refus: str = ""
    affirmations: list[Affirmation] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
    defauts: list[Defaut] = Field(default_factory=list)
    #: « service » ou « enregistrée ». Ce que la page doit afficher sans le déduire.
    origine: str = "service"


class DegradationRendue(BaseModel):
    """Ce qui manquait, et ce que son absence a coûté."""

    cause: str
    consequence: str


class ConsultationRendue(BaseModel):
    """Le résultat d'une consultation."""

    trace: str
    patient: str
    mode: Mode
    sexe: str | None = None
    age: int | None = None
    problemes: list[ProblemeRendu] = Field(default_factory=list)
    #: Vide quand aucune pathologie du périmètre n'est présente. C'est un résultat, pas un
    #: échec : n'avoir rien à demander n'est pas échouer à demander.
    requetes: list[RequeteRendue] = Field(default_factory=list)
    degradations: list[DegradationRendue] = Field(default_factory=list)


class Perimetre(BaseModel):
    """Ce que la démonstration couvre, pour que la page n'ait rien à coder en dur."""

    pathologies: list[str]
    patients: list[dict[str, str]]
    corpus: str
    avertissement: str


class Etat(BaseModel):
    """L'état du service, et celui de ses deux dépendances.

    « Je réponds » et « je réponds complètement » sont deux choses différentes : les
    confondre ferait passer une dégradation durable pour un fonctionnement normal.
    """

    #: Le processus répond. Vrai dès que la route est atteinte.
    debout: bool = True
    #: Aucune dégradation connue au démarrage.
    complet: bool = True
    terminologie: str = "indisponible"
    moteur_documentaire: str = "inconnu"
    serveur_fhir: str = ""
    traces: int = 0
