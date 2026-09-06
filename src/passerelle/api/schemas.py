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


class Interrogation(BaseModel):
    """La condition qu'un utilisateur désigne dans un dossier déjà lu.

    Le code est repris de la trace, pas fourni librement : c'est ce qui empêche la passerelle
    de devenir un moteur de recherche sur le corpus, détaché de tout dossier.
    """

    trace: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=64)


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
    #: Vrai quand la synthèse manque faute de rédaction en amont — budget, quota ou panne du
    #: fournisseur. **Distinct d'un refus** : le moteur distingue les deux, et les confondre
    #: ferait passer une indisponibilité pour une décision de se taire.
    redaction_indisponible: bool = False


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
    #: Aucune question n'est posée ici : une consultation lit un dossier, et l'utilisateur
    #: désigne ensuite la condition qui l'intéresse. Les réponses arrivent par `/interroger`.
    degradations: list[DegradationRendue] = Field(default_factory=list)


class InterrogationRendue(BaseModel):
    """Ce qu'une condition désignée a produit, et l'état de la trace après elle.

    Les dégradations rendues sont celles de la **trace entière**, pas de la seule question :
    la page en affiche un bandeau, et lui envoyer un sous-ensemble lui ferait effacer ce que
    la lecture du dossier avait déjà signalé.
    """

    trace: str
    requete: RequeteRendue
    degradations: list[DegradationRendue] = Field(default_factory=list)


class ServeurRendu(BaseModel):
    """Un serveur interrogeable, tel que la page doit le présenter.

    `posture` vient de la sonde de conformité, pas de la configuration publiée par le
    serveur : c'est l'écart entre les deux que la démonstration montre.
    """

    identifiant: str
    libelle: str
    posture: str
    ouvert_au_public: bool
    reserve: str = ""
    #: La configuration SMART a-t-elle répondu au démarrage ? Éprouvé, pas supposé.
    joignable: bool = False


class Perimetre(BaseModel):
    """Ce que la démonstration couvre, pour que la page n'ait rien à coder en dur."""

    pathologies: list[str]
    patients: list[dict[str, str]]
    serveurs: list[ServeurRendu] = Field(default_factory=list)
    #: Vrai quand aucun serveur ouvert au public n'a répondu. La page montre alors les
    #: dossiers enregistrés, et le dit — une dégradation nommée, pas un chemin parallèle.
    degradee: bool = False
    corpus: str
    avertissement: str


class EtatSmart(BaseModel):
    """Ce que la page a besoin de savoir d'un parcours d'autorisation.

    **Le jeton n'y figure pas, et ne doit jamais y figurer.** Il reste côté serveur, derrière
    un témoin de session `httponly` ; le navigateur ne porte qu'un identifiant opaque. Le
    rendre ici le mettrait à portée de n'importe quel script de la page.
    """

    autorisee: bool = False
    #: Patient auquel le jeton donne accès. Vide quand le serveur n'en a pas fourni — ce qui
    #: arrive, et que `_autoriser` traite comme un refus plutôt que comme un passe-partout.
    contexte_patient: str = ""
    scopes: str = ""
    #: Serveur FHIR visé par le parcours, pour que la page le nomme sans le coder en dur.
    serveur: str = ""
    #: Identifiant du serveur déclaré, quand le parcours en a retenu un.
    serveur_identifiant: str = ""


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
