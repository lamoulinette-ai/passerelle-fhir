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
    ),
    ServeurFhir(
        identifiant="oracle_securise",
        libelle="Oracle Health — bac à sable sécurisé",
        base="https://fhir-ehr-code.cerner.com/r4/ec2458f2-1e24-41c8-b71b-0e701af7583d",
        posture="applique les portées accordées — le seul des trois",
        ouvert_au_public=False,
        reserve="exige des identifiants personnels, hors de portée d'un visiteur",
    ),
)

#: Index par identifiant. C'est lui qui rend le choix sûr : la page nomme un serveur, jamais
#: une adresse. Accepter une base arbitraire en paramètre laisserait n'importe qui faire
#: interroger n'importe quelle adresse par la passerelle.
PAR_IDENTIFIANT = {serveur.identifiant: serveur for serveur in SERVEURS}

#: Serveur retenu à défaut de choix : le seul dont le parcours d'autorisation soit ouvert.
DEFAUT = SERVEURS[0]
