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
from passerelle.sondes import sortie

#: Requête de sondage : la lecture d'un identifiant qui n'existe pas.
#:
#: Une lecture par identifiant est la forme la plus canonique de FHIR — aucun paramètre, et
#: tous les serveurs la comprennent. `_summary=count` et les recherches paramétrées, elles,
#: se font refuser par les serveurs qui exigent un critère : mesuré sur trois serveurs, dont
#: deux ont rendu `400`.
#:
#: Elle discrimine mieux, aussi : un serveur qui exige une autorisation répond avant de
#: chercher, un serveur ouvert cherche et ne trouve rien. Et elle ne rend, par construction,
#: aucune donnée de patient.
SONDAGE = "/Patient/passerelle-sonde-identifiant-inexistant"

#: En-tête de négociation. Sans lui, certains serveurs rendent `406 Not Acceptable` — un
#: refus de format que la sonde prenait pour un refus d'autorisation.
ACCEPT = {"Accept": "application/fhir+json"}

INDETERMINE = "indéterminé"

#: Statuts qui prouvent que la requête a été **traitée** sans autorisation : le serveur a
#: cherché la ressource, qu'il l'ait trouvée ou non.
_TRAITEE = frozenset({200, 404, 410})

#: Statuts qui prouvent un refus d'autorisation.
_REFUSEE = frozenset({401, 403})

#: Tout le reste — format refusé, requête malformée, panne — ne répond pas à la question
#: posée et se consigne comme indéterminé plutôt que comme un « non ».
_VERDICTS = _TRAITEE | _REFUSEE


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
        return client.get(url, headers={**ACCEPT, **(entetes or {})}).status_code
    except httpx.HTTPError:
        return None


def _lecture_anonyme(statut: int | None) -> str:
    """La requête a-t-elle été traitée sans jeton ?

    `404` compte comme un « oui » : le serveur a cherché la ressource avant de constater son
    absence, donc il ne réclamait pas d'autorisation pour le faire.
    """
    if statut is None:
        return INDETERMINE
    if statut in _TRAITEE:
        return f"oui ({statut})"
    if statut in _REFUSEE:
        return f"non ({statut})"
    return f"{INDETERMINE} ({statut})"


def _jeton_invalide_rejete(statut: int | None) -> str:
    """Un jeton fabriqué est-il refusé, ou traité comme s'il n'était pas là ?"""
    if statut is None:
        return INDETERMINE
    if statut in _REFUSEE:
        return f"oui ({statut})"
    if statut in _TRAITEE:
        return f"non ({statut})"
    return f"{INDETERMINE} ({statut})"


def observer(
    base: str,
    jeton: str = "",
    patient_hors_contexte: str = "",
    client: httpx.Client | None = None,
    chemin_sondage: str = "",
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

        sondage = f"{racine}{chemin_sondage or SONDAGE}"
        statut = _statut(client, sondage)
        constat.lecture_anonyme = _lecture_anonyme(statut)
        constat.jeton_invalide_rejete = _jeton_invalide_rejete(
            _statut(client, sondage, {"Authorization": "Bearer jeton-invalide"})
        )
        # Un statut hors verdict vient souvent du sondage lui-même : tous les serveurs FHIR
        # n'implémentent pas `_summary=count`. Le dire évite qu'une case indéterminée passe
        # pour une propriété du serveur.
        if statut is not None and statut not in _VERDICTS:
            constat.remarques.append(
                f"le sondage « {chemin_sondage or SONDAGE} » a rendu {statut} — ce serveur ne "
                "le prend peut-être pas en charge ; réessayer avec --sondage"
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
        "--sondage",
        default="",
        help=f"requête de sondage, à défaut « {SONDAGE} » — certains serveurs la refusent",
    )
    analyseur.add_argument(
        "--autoriser", action="store_true", help="obtenir un jeton par le parcours SMART"
    )
    sortie.declarer(analyseur)
    arguments = analyseur.parse_args()

    sortie.delier_de_la_console()
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

    constat = observer(
        arguments.base, jeton, arguments.autre_patient, chemin_sondage=arguments.sondage
    )
    rendu = (
        json.dumps(constat.model_dump(), ensure_ascii=False, indent=2)
        if arguments.json
        else en_markdown(constat)
    )
    sortie.publier(rendu, arguments.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
