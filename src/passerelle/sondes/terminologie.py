"""Ce que les dossiers de démonstration contiennent, et ce que la passerelle en fait.

Un chiffre : le **taux de correspondance** — part des codes SNOMED rendus par le serveur
FHIR qui obtiennent une désignation française avérée. Un `display` revient dans tous les
cas, y compris pour un concept jamais traduit ; seule l'existence d'une désignation de
langue française compte, faute de quoi le taux serait de cent pour cent dont une part
d'anglais déguisé.

La sonde nomme aussi la version du référentiel : un libellé sans version n'est pas
reproductible.

Et elle rend, **patient par patient, les pathologies réellement appariées**. C'est ce relevé
qui fait foi pour les descriptions de `api/patients.py` : écrites à la main, elles ont menti
dès que le périmètre a changé, sans que rien ne le signale.
"""

from __future__ import annotations

import argparse
import json
import sys

from passerelle.api.patients import PATIENTS
from passerelle.fhir.client import ClientFhir, FhirIndisponible
from passerelle.fhir.contexte import contexte as assembler
from passerelle.requete.gabarits import apparier
from passerelle.requete.perimetre import SYSTEME_SNOMED, pathologie
from passerelle.sondes import sortie
from passerelle.terminologie.client import Terminologie, TerminologieIndisponible


def _dossiers() -> list[dict[str, object]]:
    """Lit chaque dossier de démonstration et relève ce que la passerelle en tirerait.

    L'appariement passe par `apparier`, et non par une comparaison de codes refaite ici :
    seules les conditions **actives** entrent au périmètre déclaré, et recompter autrement
    produirait un relevé qui ne décrit pas ce que le périmètre couvre.
    """
    client, dossiers = ClientFhir(), []
    try:
        for patient in PATIENTS:
            try:
                contexte = assembler(
                    client.patient(patient.identifiant),
                    client.conditions(patient.identifiant),
                )
            except FhirIndisponible as erreur:
                print(f"{patient.identifiant} : {erreur}", file=sys.stderr)
                continue
            dossiers.append(
                {
                    "libelle": patient.libelle,
                    "illustre": patient.illustre,
                    "conditions": len(contexte.problemes),
                    "pathologies": sorted(apparier(contexte)),
                    "codes": [(p.code.systeme, p.code.code) for p in contexte.problemes],
                }
            )
    finally:
        client.fermer()
    return dossiers


def _codes_distincts(dossiers: list[dict[str, object]]) -> list[tuple[str, str]]:
    """Les codes rencontrés une seule fois chacun, dans l'ordre où ils sont apparus."""
    vus: list[tuple[str, str]] = []
    for dossier in dossiers:
        for paire in dossier["codes"]:  # type: ignore[union-attr]
            if paire not in vus:
                vus.append(paire)
    return vus


def mesurer(codes: list[tuple[str, str]]) -> dict[str, object]:
    """Résout chaque code et rend le relevé."""
    terminologie = Terminologie()
    resolus, non_resolus, injoignables, apparies = [], [], [], []
    versions: set[str] = set()
    try:
        for systeme, code in codes:
            try:
                concept = terminologie.resoudre(systeme, code)
            except TerminologieIndisponible:
                injoignables.append(code)
                continue
            if concept.version:
                versions.add(concept.version)
            (resolus if concept.resolu else non_resolus).append(
                {"code": code, "libelle": concept.libelle}
            )

            if pathologie(systeme, code) is not None:
                apparies.append(code)
    finally:
        terminologie.fermer()

    eprouves = len(resolus) + len(non_resolus)
    return {
        "codes_distincts": len(codes),
        "eprouves": eprouves,
        "injoignables": injoignables,
        "resolus": len(resolus),
        "taux": round(len(resolus) / eprouves, 3) if eprouves else None,
        "resolus_detail": resolus,
        "non_resolus": non_resolus,
        "apparies_au_perimetre": len(apparies),
        "versions": sorted(versions),
    }


def patients_en_markdown(dossiers: list[dict[str, object]]) -> str:
    """Rend, patient par patient, ce que la passerelle tire réellement du dossier."""
    lignes = [
        "**Ce que chaque patient de démonstration déclenche**",
        "",
        "| patient | conditions lues | pathologies appariées | requêtes |",
        "| --- | ---: | --- | ---: |",
    ]
    for dossier in dossiers:
        pathologies = dossier["pathologies"]
        lignes.append(
            f"| {dossier['libelle']} | {dossier['conditions']} "
            f"| {', '.join(pathologies) or '—'} | {len(pathologies)} |"  # type: ignore[arg-type]
        )
    lignes += [
        "",
        "La colonne « pathologies appariées » fait foi pour les descriptions de "
        "`api/patients.py`. Un écart entre les deux est un libellé à corriger, pas une "
        "mesure à réinterpréter.",
        "",
    ]
    return "\n".join(lignes)


def en_markdown(releve: dict[str, object]) -> str:
    """Rend le relevé en tableau collable."""
    taux = releve["taux"]
    lignes = [
        "| mesure | valeur |",
        "| --- | ---: |",
        f"| codes distincts rencontrés | {releve['codes_distincts']} |",
        f"| codes éprouvés | {releve['eprouves']} |",
        f"| **libellé français obtenu** | **{releve['resolus']}** |",
        f"| **taux de correspondance** | **{'—' if taux is None else f'{taux:.1%}'}** |",
        f"| codes appariés au périmètre | {releve['apparies_au_perimetre']} |",
    ]
    versions = releve["versions"]
    if versions:
        lignes += ["", "Version du référentiel : " + ", ".join(versions)]
    manquants = releve["non_resolus"]
    if manquants:
        lignes += ["", "**Sans désignation française :**", ""]
        lignes += [f"- `{m['code']}` — {m['libelle'] or '(aucun libellé)'}" for m in manquants]

    # Le libellé seul ne permet pas de revenir au concept : sans son code, on ne peut ni
    # vérifier une traduction douteuse, ni la signaler à qui la publie.
    detail = releve["resolus_detail"]
    if detail:
        lignes += ["", "**Codes et libellés retenus**", "", "| code | libellé |", "| --- | --- |"]
        lignes += [f"| `{d['code']}` | {d['libelle']} |" for d in detail]
    return "\n".join(lignes)


def designations(systeme: str, code: str) -> str:
    """Rend **toutes** les désignations d'un concept, avec leur langue et leur usage.

    `resoudre` retient la première désignation de langue française. Si le serveur en rend
    plusieurs — nom pleinement spécifié, synonyme préféré, synonymes — ce choix décide du
    libellé affiché, et rien ne dit qu'il tombe sur le bon. Cette vue le montre.
    """
    terminologie = Terminologie()
    try:
        charge = terminologie.charge(systeme, code)
    finally:
        terminologie.fermer()

    lignes = [f"**`{code}` — toutes les désignations rendues par `$lookup`**", ""]
    for nom in ("display", "name", "version"):
        for parametre in charge.get("parameter", []):
            if parametre.get("name") == nom:
                valeur = parametre.get("valueString") or parametre.get("valueCode") or ""
                lignes.append(f"- `{nom}` : {valeur}")
    lignes += ["", "| langue | usage | valeur |", "| --- | --- | --- |"]
    for parametre in charge.get("parameter", []):
        if parametre.get("name") != "designation":
            continue
        parts = {p.get("name"): p for p in parametre.get("part", [])}
        usage = parts.get("use", {}).get("valueCoding", {}) or {}
        lignes.append(
            f"| {parts.get('language', {}).get('valueCode', '')} "
            f"| {usage.get('display') or usage.get('code') or ''} "
            f"| {parts.get('value', {}).get('valueString', '')} |"
        )
    lignes += [
        "",
        "`resoudre` retient **la première ligne de langue française**. Si une autre porte le "
        "synonyme préféré, c'est elle qu'il faudrait lire — et le taux de correspondance "
        "compte alors des concepts résolus dont le libellé affiché est le mauvais.",
    ]
    return "\n".join(lignes)


def main() -> int:
    """Point d'entrée `sonde-terminologie`."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "--concept", default="", help="vider les désignations d'un seul code, sans autre mesure"
    )
    sortie.declarer(analyseur)
    arguments = analyseur.parse_args()

    sortie.delier_de_la_console()
    if arguments.concept:
        sortie.publier(designations(SYSTEME_SNOMED, arguments.concept), arguments.sortie)
        return 0

    dossiers = _dossiers()
    codes = _codes_distincts(dossiers)
    print(f"{len(dossiers)} dossiers, {len(codes)} codes distincts…", file=sys.stderr)
    releve = mesurer(codes)
    releve["patients"] = dossiers
    rendu = (
        json.dumps(releve, ensure_ascii=False, indent=2)
        if arguments.json
        else patients_en_markdown(dossiers) + "\n" + en_markdown(releve)
    )
    sortie.publier(rendu, arguments.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
