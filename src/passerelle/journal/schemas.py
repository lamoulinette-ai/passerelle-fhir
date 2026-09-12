"""Modèles de la trace de traçabilité.

Une requête produit **une** trace, et non des lignes de journal à recoudre. Chaque section
répond à une question qu'un auditeur pose : d'où venait le dossier, sous quelle autorisation
il a été lu, ce qui a été vu, ce sur quoi on a agi, et pourquoi pas le reste.

Comme le contexte patient, la trace n'a aucun champ où loger un nom, une adresse ou un
numéro — et la contrainte est plus stricte ici, puisque les traces sont exportées.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Frontiere(StrEnum):
    """Au nom de quoi une lecture a été faite.

    La distinction est l'objet même du journal : une autorisation déléguée dit ce que
    l'utilisateur avait le droit de lire, une créance de service dit ce que la passerelle
    est allée chercher en son nom. Les confondre effacerait la seule information qu'un
    auditeur cherche.
    """

    DELEGUEE = "autorisation déléguée"
    SERVICE = "créance de service"
    AUCUNE = "aucune"


class Mode(StrEnum):
    """D'où vient le contexte patient."""

    DEMONSTRATION = "démonstration"
    SMART = "SMART"


class Acces(BaseModel):
    """Une lecture faite vers un service extérieur."""

    ressource: str
    origine: str
    frontiere: Frontiere
    autorisation: str = ""
    statut: str = "obtenu"


class ProblemeObserve(BaseModel):
    """Un problème lu dans le dossier, résolu ou non.

    `dans_le_perimetre` ne dit pas qu'un problème a été retenu — aucun ne l'est, tous sont
    interrogeables. Il dit sous quelle tournure la question serait posée : une formulation
    mesurée contre le corpus, ou la forme libre. C'est ce qui permet de relire une réponse
    en sachant ce qui la précédait.
    """

    systeme: str
    code: str
    libelle_source: str = ""
    libelle_fr: str | None = None
    terminologie: str = ""
    version: str = ""
    statut: str = ""
    dans_le_perimetre: bool = False

    @property
    def resolu(self) -> bool:
        return bool(self.libelle_fr)


class PassageCite(BaseModel):
    """Un passage rendu par le moteur documentaire, et de quoi le retrouver.

    Plusieurs passages viennent souvent du même document : c'est le numéro et la page qui
    les distinguent, et les taire ferait passer cinq extraits pour cinq documents.
    """

    numero: int
    document: str
    page: int
    titre: str = ""


class Interrogation(BaseModel):
    """Une question posée au moteur documentaire, et ce qu'elle a rendu.

    Une par pathologie appariée. Les regrouper en champs uniques ferait perdre toutes les
    questions sauf la dernière, et attribuerait à celle-ci les passages des précédentes.
    """

    gabarit: str
    question: str
    codes: list[str] = Field(default_factory=list)
    issue: str = ""
    #: « service » ou « enregistrée ».
    origine: str = "service"
    #: La synthèse manquait-elle faute de rédaction en amont ? Un refus légitime et une
    #: rédaction coupée produisent la même issue ; seul ce drapeau les sépare.
    redaction_indisponible: bool = False
    passages: list[PassageCite] = Field(default_factory=list)
    #: Motifs des contrôles mécaniques du moteur — citation hors périmètre, quantité absente.
    defauts: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    """Ce que la passerelle a refusé d'elle-même, et pourquoi.

    Le serveur amont n'applique pas toujours les scopes qu'il accorde. Ce qu'il laisse
    passer et que la passerelle refuse tout de même n'a aucune trace ailleurs qu'ici.
    """

    objet: str
    motif: str


class Degradation(BaseModel):
    """Ce qui manquait, et ce que son absence a coûté."""

    cause: str
    consequence: str


class Trace(BaseModel):
    """Le dossier de traçabilité d'une requête."""

    identifiant: str
    horodatage: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: Mode = Mode.DEMONSTRATION
    contexte_patient: str = ""
    scopes_accordes: list[str] = Field(default_factory=list)
    acces: list[Acces] = Field(default_factory=list)
    problemes: list[ProblemeObserve] = Field(default_factory=list)
    interrogations: list[Interrogation] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    degradations: list[Degradation] = Field(default_factory=list)

    @property
    def taux_de_resolution(self) -> float | None:
        """Part des codes ayant reçu un libellé français, ou `None` s'il n'y en avait aucun."""
        if not self.problemes:
            return None
        return sum(1 for p in self.problemes if p.resolu) / len(self.problemes)

    @property
    def degrade(self) -> bool:
        """Vrai si au moins une dégradation a été consignée."""
        return bool(self.degradations)
