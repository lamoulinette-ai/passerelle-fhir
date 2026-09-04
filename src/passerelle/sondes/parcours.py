"""Obtention d'un jeton en ligne de commande, par recopie de l'URL de retour.

La sonde n'a pas de navigateur ni de serveur de redirection : elle affiche l'URL
d'autorisation, l'opérateur la suit, puis recolle l'URL sur laquelle il a atterri. Le code
et l'état s'y lisent, et l'échange se fait normalement.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx

from passerelle.smart.autorisation import AutorisationRefusee, demander, echanger
from passerelle.smart.decouverte import decouvrir
from passerelle.smart.schemas import Jeton

#: Redirection annoncée au serveur. Aucun service ne l'écoute : l'opérateur recopie l'URL.
REDIRECTION_DEFAUT = "http://localhost:8006/smart/retour"


def _parametre(url: str, nom: str) -> str:
    """Lit un paramètre de requête dans une URL de retour."""
    valeurs = parse_qs(urlparse(url).query).get(nom, [])
    return valeurs[0] if valeurs else ""


def autoriser(
    base: str,
    redirection: str = REDIRECTION_DEFAUT,
    client: httpx.Client | None = None,
    demander_url: object = input,
) -> Jeton:
    """Déroule le parcours d'autorisation et rend le jeton obtenu."""
    configuration = decouvrir(base, client=client)
    demande = demander(configuration, base, redirection)

    print("\nOuvrez cette adresse, menez le parcours à son terme :\n")
    print(demande.url)
    print("\nPuis recopiez ici l'adresse sur laquelle vous avez atterri.")
    retour = str(demander_url("adresse de retour > ")).strip()  # type: ignore[operator]

    erreur = _parametre(retour, "error")
    if erreur:
        raise AutorisationRefusee(f"le serveur a refusé : {erreur}")

    code = _parametre(retour, "code")
    if not code:
        raise AutorisationRefusee("aucun code dans l'adresse de retour")

    return echanger(configuration, demande, code, _parametre(retour, "state"), redirection, client)
