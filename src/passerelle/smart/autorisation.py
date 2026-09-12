"""Parcours d'autorisation SMART on FHIR, client public avec PKCE.

La passerelle n'est pas un client confidentiel : aucun secret n'est détenu, et c'est le
vérificateur PKCE qui lie la demande d'autorisation à l'échange du code.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from urllib.parse import urlencode

import httpx

from passerelle.smart.schemas import (
    SCOPES_DEFAUT,
    SCOPES_EHR_DEFAUT,
    ConfigurationSmart,
    Demande,
    Jeton,
)

journal = logging.getLogger("passerelle.smart")

CLIENT_DEFAUT = "passerelle-fhir"


class AutorisationRefusee(RuntimeError):
    """Le serveur d'autorisation a refusé la demande, ou l'échange a échoué."""


def client_id() -> str:
    """Identifiant de client, lu dans l'environnement.

    Le repli est annoncé : un serveur qui exige l'enregistrement de l'application refuse
    l'identifiant par défaut, et son message ne nomme pas la variable qui manquait.
    """
    declare = os.environ.get("PASSERELLE_SMART_CLIENT_ID", "").strip()
    if declare:
        return declare
    journal.warning(
        "PASSERELLE_SMART_CLIENT_ID absent — repli sur « %s », que tout serveur exigeant "
        "un enregistrement refusera",
        CLIENT_DEFAUT,
    )
    return CLIENT_DEFAUT


def scopes(ehr: bool = False) -> str:
    """Scopes demandés, lus dans l'environnement.

    Les deux modes de lancement ne demandent pas la même portée de contexte : `launch`
    quand le dossier fournit un jeton de lancement, `launch/patient` quand il faut que le
    serveur d'autorisation désigne lui-même le patient.
    """
    if ehr:
        return os.environ.get("PASSERELLE_SMART_SCOPES_EHR", "").strip() or SCOPES_EHR_DEFAUT
    return os.environ.get("PASSERELLE_SMART_SCOPES", "").strip() or SCOPES_DEFAUT


def _sans_bourrage(brut: bytes) -> str:
    """Encode en base64url sans caractère de bourrage, comme l'exige RFC 7636."""
    return base64.urlsafe_b64encode(brut).decode("ascii").rstrip("=")


def verificateur() -> str:
    """Engendre un vérificateur PKCE."""
    return _sans_bourrage(secrets.token_bytes(32))


def empreinte(verif: str) -> str:
    """Rend le `code_challenge` S256 d'un vérificateur."""
    return _sans_bourrage(hashlib.sha256(verif.encode("ascii")).digest())


def demander(
    configuration: ConfigurationSmart,
    base: str,
    redirection: str,
    lancement: str | None = None,
    portees: str = "",
) -> Demande:
    """Construit l'URL d'autorisation et l'état à conserver jusqu'au retour.

    La présence de `lancement` décide du mode : elle ajoute le paramètre `launch` et
    commande les scopes, les deux allant toujours ensemble.

    `portees` l'emporte sur l'environnement quand il est fourni. Le chemin vif ne s'en sert
    pas : c'est aux sondes qu'il faut pouvoir demander une liste de portées choisie, sans
    quoi elles ne mesureraient que la configuration déployée.
    """
    if not configuration.pkce_s256:
        journal.warning("le serveur n'annonce pas PKCE S256 — la demande le propose tout de même")

    verif, etat = verificateur(), secrets.token_urlsafe(16)
    parametres = {
        "response_type": "code",
        "client_id": client_id(),
        "scope": portees or scopes(ehr=bool(lancement)),
        "redirect_uri": redirection,
        "aud": base,
        "state": etat,
        "code_challenge": empreinte(verif),
        "code_challenge_method": "S256",
    }
    if lancement:
        parametres["launch"] = lancement
    return Demande(
        url=f"{configuration.authorization_endpoint}?{urlencode(parametres)}",
        etat=etat,
        verificateur=verif,
    )


def echanger(
    configuration: ConfigurationSmart,
    demande: Demande,
    code: str,
    etat: str,
    redirection: str,
    client: httpx.Client | None = None,
) -> Jeton:
    """Échange un code d'autorisation contre un jeton, après contrôle de l'état."""
    if not secrets.compare_digest(etat, demande.etat):
        raise AutorisationRefusee("état discordant — la réponse ne correspond pas à la demande")

    ferme = client is None
    client = client or httpx.Client(timeout=10.0)
    corps = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirection,
        "client_id": client_id(),
        "code_verifier": demande.verificateur,
    }
    try:
        reponse = client.post(
            configuration.token_endpoint,
            data=corps,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        reponse.raise_for_status()
        charge = reponse.json()
    except httpx.HTTPError as erreur:
        raise AutorisationRefusee(f"échange refusé : {erreur}") from erreur
    except ValueError as erreur:
        raise AutorisationRefusee("échange refusé : réponse illisible") from erreur
    finally:
        if ferme:
            client.close()

    if "error" in charge:
        raise AutorisationRefusee(f"échange refusé : {charge.get('error')}")

    jeton = Jeton.model_validate(charge)
    journal.info(
        "jeton obtenu — scopes accordés : %s, contexte patient : %s",
        jeton.scope or "aucun",
        jeton.patient or "aucun",
    )
    return jeton
