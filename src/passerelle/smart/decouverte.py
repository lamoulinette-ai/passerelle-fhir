"""Découverte des points d'entrée d'autorisation d'un serveur FHIR.

Limite connue : seul `.well-known/smart-configuration` est lu. Certains serveurs ne
publient leurs points d'entrée que dans l'extension `oauth-uris` du `CapabilityStatement` ;
ceux-là ne sont pas encore pris en charge.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from passerelle.smart.schemas import ConfigurationSmart

journal = logging.getLogger("passerelle.smart")

CHEMIN = "/.well-known/smart-configuration"


class DecouverteImpossible(RuntimeError):
    """Le serveur ne publie pas de configuration SMART exploitable."""


def decouvrir(base: str, client: httpx.Client | None = None) -> ConfigurationSmart:
    """Lit la configuration SMART publiée par une base FHIR."""
    url = f"{base.rstrip('/')}{CHEMIN}"
    ferme = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        reponse = client.get(url, headers={"Accept": "application/json"})
        reponse.raise_for_status()
        charge = reponse.json()
    except httpx.HTTPError as erreur:
        raise DecouverteImpossible(f"{url} : {erreur}") from erreur
    except ValueError as erreur:
        raise DecouverteImpossible(f"{url} : réponse illisible") from erreur
    finally:
        if ferme:
            client.close()

    try:
        configuration = ConfigurationSmart.model_validate(charge)
    except ValidationError as erreur:
        raise DecouverteImpossible(f"{url} : configuration incomplète — {erreur}") from erreur

    journal.info(
        "SMART découvert sur %s — PKCE S256 : %s, lancement autonome : %s",
        base,
        configuration.pkce_s256,
        configuration.lancement_autonome,
    )
    return configuration
