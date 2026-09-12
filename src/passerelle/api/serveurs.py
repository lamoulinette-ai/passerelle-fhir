"""Les serveurs FHIR de la démonstration, déclarés avec ce qu'ils appliquent vraiment.

Ce fichier existe parce que ces trois adresses n'étaient nulle part. Le tableau des postures
avait été produit par la sonde de conformité, ses résultats consignés — mais pas les bases
qui les avaient rendus. La mesure n'était donc pas reproductible : il a fallu retrouver une
URL sur le web plusieurs heures après l'avoir interrogée.

**`posture` dit ce que la sonde a mesuré, jamais ce que le serveur annonce.** La distinction
est l'objet même de ce projet : le lanceur publie « lancement autonome » dans sa
configuration, et son point d'autorisation refusait pourtant la demande tant que l'adresse ne
portait pas d'options de lancement encodées.
"""

from __future__ import annotations

from pydantic import BaseModel


class ServeurFhir(BaseModel):
    """Un serveur FHIR interrogeable, et ce qu'on a constaté en l'interrogeant."""

    identifiant: str
    libelle: str
    base: str
    #: Ce que la sonde de conformité a observé, en une phrase.
    posture: str
    #: Le visiteur peut-il mener le parcours d'autorisation sans compte à lui ?
    ouvert_au_public: bool
    #: Ce qui manque ou ce qui gêne, quand quelque chose manque ou gêne.
    reserve: str = ""
    #: Le serveur se lit-il sans parcours d'autorisation ?
    #:
    #: Vrai quand il n'a aucune couche d'autorisation. Distinct de `ouvert_au_public`, qui
    #: dit qu'un parcours est menable sans compte : ici, il n'y a pas de parcours du tout, et
    #: la page n'a donc aucune connexion à proposer ni à griser.
    lecture_directe: bool = False
    #: Portées demandées à ce serveur. Vide, celles de la configuration s'appliquent.
    #:
    #: Elles ne peuvent pas être communes : le préfixe `patient/` désigne le patient d'un
    #: contexte de lancement, et n'a de sens que si le serveur en fournit un. Là où il n'en
    #: fournit pas, c'est `user/` qu'il faut demander — ce que le praticien connecté a le
    #: droit de voir. Mesuré serveur par serveur, jamais supposé.
    portees: str = ""


SERVEURS: tuple[ServeurFhir, ...] = (
    ServeurFhir(
        identifiant="lanceur",
        libelle="SMART App Launcher",
        # Le segment `sim/e30` porte des options de lancement vides mais valides — `e30` est
        # `{}` en base64url. Sans lui, le point d'autorisation tente de décoder une chaîne
        # vide et refuse la demande. Mesuré : avec, l'écran de choix de patient s'affiche.
        base="https://launch.smarthealthit.org/v/r4/sim/e30/fhir",
        posture="valide un jeton présenté, sans en exiger aucun pour lire",
        ouvert_au_public=True,
        reserve="simulateur, non un serveur d'établissement",
    ),
    ServeurFhir(
        identifiant="oracle_ouvert",
        libelle="Oracle Health — bac à sable ouvert",
        base="https://fhir-open.cerner.com/r4/ec2458f2-1e24-41c8-b71b-0e701af7583d",
        posture="aucune couche d'autorisation — ignore jusqu'aux jetons fabriqués",
        ouvert_au_public=False,
        reserve="lecture directe, sans parcours d'autorisation à mener",
        lecture_directe=True,
    ),
    ServeurFhir(
        identifiant="oracle_securise",
        libelle="Oracle Health — bac à sable sécurisé",
        base="https://fhir-ehr-code.cerner.com/r4/ec2458f2-1e24-41c8-b71b-0e701af7583d",
        posture="applique les portées accordées — le seul des trois",
        ouvert_au_public=False,
        reserve="exige des identifiants personnels, hors de portée d'un visiteur",
        # Ce serveur ne propose pas de sélecteur de patient à une persona `provider` : une
        # demande préfixée `patient/` s'y fait refuser, faute de contexte à désigner. Le
        # relevé de `sonde-oracle` porte la liste accordée telle qu'elle a été obtenue.
        portees="user/Patient.read user/Condition.read openid fhirUser",
    ),
)

#: Index par identifiant. C'est lui qui rend le choix sûr : la page nomme un serveur, jamais
#: une adresse. Accepter une base arbitraire en paramètre laisserait n'importe qui faire
#: interroger n'importe quelle adresse par la passerelle.
PAR_IDENTIFIANT = {serveur.identifiant: serveur for serveur in SERVEURS}

#: Index par base FHIR, normalisée sans barre oblique finale.
#:
#: Un lancement depuis un dossier patient annonce le serveur par son adresse — le paramètre
#: `iss` de la spécification — et non par un identifiant. Cet index la ramène à un serveur
#: déclaré : la garde de `PAR_IDENTIFIANT` tient donc aussi pour ce mode, une adresse
#: absente d'ici n'étant jamais visitée.
PAR_BASE = {serveur.base.rstrip("/"): serveur for serveur in SERVEURS}

#: Serveur retenu à défaut de choix : le seul dont le parcours d'autorisation soit ouvert.
DEFAUT = SERVEURS[0]
