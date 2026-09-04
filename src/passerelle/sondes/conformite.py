"""Ce qu'un serveur FHIR annonce, et ce qu'il applique réellement.

La sonde émet une poignée de requêtes, toutes en lecture, jamais en boucle : elle interroge
des bacs à sable mis à disposition des développeurs, pas des serveurs à éprouver en charge.

Les cinq premières observations n'exigent rien. La sixième — l'application du scope — demande
un jeton, et c'est la seule qui distingue un serveur d'exercice d'un serveur réel.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx
from pydantic import BaseModel, Field

from passerelle.smart.autorisation import AutorisationRefusee
from passerelle.smart.decouverte import DecouverteImpossible, decouvrir

#: Requête de sondage : un décompte ne rend aucune donnée de patient.
SONDAGE = "/Patient?_summary=count"

INDETERMINE = "indéterminé"


class Constat(BaseModel):
    """Ce que la sonde a observé sur une base."""

    base: str
    decouverte: bool = False
    autorisation: str = ""
    jeton_url: str = ""
    pkce_s256: bool = False
    lancement_autonome: bool = False
    scopes_v1: bool = False
    scopes_v2: bool = False
    lecture_anonyme: str = INDETERMINE
    jeton_invalide_rejete: str = INDETERMINE
    scope_applique: str = INDETERMINE
    remarques: list[str] = Field(default_factory=list)


def _statut(client: httpx.Client, url: str, entetes: dict[str, str] | None = None) -> int | None:
    """Rend le statut d'un `GET`, ou `None` si la requête n'aboutit pas."""
    try:
        return client.get(url, headers=entetes or {}).status_code
    except httpx.HTTPError:
        return None


def _oui_non(statut: int | None, attendu: int) -> str:
    """Traduit un statut en constat lisible."""
    if statut is None:
        return INDETERMINE
    return "oui" if statut == attendu else f"non ({statut})"


def observer(
    base: str,
    jeton: str = "",
    patient_hors_contexte: str = "",
    client: httpx.Client | None = None,
) -> Constat:
    """Observe une base FHIR et rend ce qui a été constaté."""
    racine = base.rstrip("/")
    constat = Constat(base=racine)
    ferme = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=False)

    try:
        try:
            configuration = decouvrir(racine, client=client)
        except DecouverteImpossible as erreur:
            constat.remarques.append(f"découverte impossible : {erreur}")
        else:
            constat.decouverte = True
            constat.autorisation = configuration.authorization_endpoint
            constat.jeton_url = configuration.token_endpoint
            constat.pkce_s256 = configuration.pkce_s256
            constat.lancement_autonome = configuration.lancement_autonome
            constat.scopes_v1 = "permission-v1" in configuration.capabilities
            constat.scopes_v2 = "permission-v2" in configuration.capabilities

        sondage = f"{racine}{SONDAGE}"
        constat.lecture_anonyme = _oui_non(_statut(client, sondage), 200)
        constat.jeton_invalide_rejete = _oui_non(
            _statut(client, sondage, {"Authorization": "Bearer jeton-invalide"}), 401
        )

        if jeton and patient_hors_contexte:
            statut = _statut(
                client,
                f"{racine}/Patient/{patient_hors_contexte}",
                {"Authorization": f"Bearer {jeton}"},
            )
            if statut is None:
                constat.scope_applique = INDETERMINE
            elif statut == 200:
                constat.scope_applique = "non — un patient hors contexte est lisible"
            elif statut in (401, 403):
                constat.scope_applique = f"oui ({statut})"
            else:
                constat.scope_applique = f"indéterminé ({statut})"
        else:
            constat.remarques.append(
                "application du scope non éprouvée — il y faut un jeton et un patient hors contexte"
            )
    finally:
        if ferme:
            client.close()

    return constat


def _ligne(libelle: str, valeur: object) -> str:
    if isinstance(valeur, bool):
        valeur = "oui" if valeur else "non"
    return f"| {libelle} | {valeur or '—'} |"


def en_markdown(constat: Constat) -> str:
    """Rend le constat en tableau collable dans un README."""
    v1 = "v1" if constat.scopes_v1 else "—"
    v2 = "v2" if constat.scopes_v2 else "—"
    lignes = [
        f"**{constat.base}**",
        "",
        "| observation | constat |",
        "| --- | --- |",
        _ligne("configuration SMART publiée", constat.decouverte),
        _ligne("PKCE S256 annoncé", constat.pkce_s256),
        _ligne("lancement autonome annoncé", constat.lancement_autonome),
        _ligne("syntaxe de scopes v1 / v2", f"{v1} / {v2}"),
        _ligne("lecture sans jeton autorisée", constat.lecture_anonyme),
        _ligne("jeton invalide rejeté", constat.jeton_invalide_rejete),
        _ligne("**scope appliqué**", constat.scope_applique),
    ]
    if constat.remarques:
        lignes += ["", *(f"- {remarque}" for remarque in constat.remarques)]
    return "\n".join(lignes)


def main() -> int:
    """Point d'entrée `sonde-conformite`."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("base", help="base FHIR à observer")
    analyseur.add_argument("--jeton", default="", help="jeton d'accès valide")
    analyseur.add_argument("--autre-patient", default="", help="patient hors du contexte du jeton")
    analyseur.add_argument(
        "--autoriser", action="store_true", help="obtenir un jeton par le parcours SMART"
    )
    analyseur.add_argument("--json", action="store_true", help="rendre le constat en JSON")
    arguments = analyseur.parse_args()

    jeton = arguments.jeton
    if arguments.autoriser:
        from passerelle.sondes.parcours import autoriser

        try:
            obtenu = autoriser(arguments.base)
        except (AutorisationRefusee, DecouverteImpossible) as erreur:
            print(f"parcours interrompu : {erreur}", file=sys.stderr)
            return 1
        jeton = obtenu.access_token
        print(f"\njeton obtenu — contexte patient : {obtenu.patient or 'aucun'}\n", file=sys.stderr)

    constat = observer(arguments.base, jeton, arguments.autre_patient)
    if arguments.json:
        print(json.dumps(constat.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(en_markdown(constat))
    return 0


if __name__ == "__main__":
    sys.exit(main())
