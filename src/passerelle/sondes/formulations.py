"""Quelle formulation obtient une réponse, et laquelle se fait refuser.

Le premier gabarit écrit — « quelle est la prise en charge recommandée de X ? » — s'est fait
refuser sur les trois pathologies, alors que la recherche rendait les bons documents. Le
motif était le même à chaque fois : dix extraits ne constituent pas des recommandations
générales et complètes.

Cette sonde mesure ce qui n'avait pas à être deviné. Elle interroge le service une fois par
couple (pathologie, formulation) et rend l'issue obtenue.
"""

from __future__ import annotations

import argparse
import json
import sys

from passerelle.documentaliste.client import Documentaliste
from passerelle.documentaliste.schemas import Reponse
from passerelle.requete.gabarits import Forme, texte
from passerelle.requete.perimetre import PATHOLOGIES
from passerelle.sondes import sortie


def _observer(reponse: Reponse | None, cause: str) -> dict[str, object]:
    """Réduit une réponse à ce qui distingue une formulation d'une autre."""
    if reponse is None:
        return {"issue": "indéterminé", "cause": cause}
    passages = reponse.passages
    return {
        "issue": reponse.issue,
        "affirmations": len(reponse.affirmations),
        "passages": len(passages),
        "premier": (passages[0].titre or passages[0].document) if passages else "",
        "refus": reponse.refus[:120],
        "redaction_indisponible": reponse.redaction_indisponible,
    }


def balayer(formes: list[Forme]) -> dict[str, dict[str, dict[str, object]]]:
    """Interroge le service pour chaque couple (pathologie, formulation)."""
    moteur, releve = Documentaliste(), {}
    try:
        for patho in PATHOLOGIES:
            par_forme: dict[str, dict[str, object]] = {}
            for forme in formes:
                question = texte(patho, forme)
                reponse, cause = moteur.interroger(question)
                observe = _observer(reponse, cause)
                observe["question"] = question
                par_forme[forme.name] = observe
                print(f"  {patho.identifiant:24s} {forme.name:16s} {observe['issue']}")
            releve[patho.identifiant] = par_forme
    finally:
        moteur.fermer()
    return releve


def en_markdown(releve: dict[str, dict[str, dict[str, object]]]) -> str:
    """Rend le relevé en tableaux collables."""
    lignes: list[str] = []
    for pathologie, par_forme in releve.items():
        lignes += [
            f"**{pathologie}**",
            "",
            "| formulation | issue | affirmations | passages | premier document |",
            "| --- | --- | ---: | ---: | --- |",
        ]
        for nom, observe in par_forme.items():
            lignes.append(
                f"| {nom} | {observe.get('issue')} | {observe.get('affirmations', '—')} "
                f"| {observe.get('passages', '—')} | {str(observe.get('premier', ''))[:60]} |"
            )
        lignes.append("")
    return "\n".join(lignes)


def main() -> int:
    """Point d'entrée `sonde-formulations`."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "--formes",
        nargs="*",
        default=[forme.name for forme in Forme],
        help="noms des formulations à mesurer",
    )
    sortie.declarer(analyseur)
    arguments = analyseur.parse_args()

    sortie.delier_de_la_console()
    try:
        formes = [Forme[nom] for nom in arguments.formes]
    except KeyError as erreur:
        print(f"formulation inconnue : {erreur}", file=sys.stderr)
        return 1

    print(f"{len(PATHOLOGIES) * len(formes)} interrogations…", file=sys.stderr)
    releve = balayer(formes)
    rendu = (
        json.dumps(releve, ensure_ascii=False, indent=2) if arguments.json else en_markdown(releve)
    )
    sortie.publier(rendu, arguments.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
