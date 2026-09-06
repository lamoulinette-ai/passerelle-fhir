"""Quels dossiers du bac à sable portent plusieurs pathologies du périmètre.

Le cas à deux requêtes a disparu de la démonstration quand le périmètre s'est resserré. Il
est le seul à montrer ce que la trace fait d'une consultation : une interrogation par
question posée, et non une question écrasant la précédente.

**On cherche par code, pas en balayant les dossiers.** Interroger `Condition?code=…` pour
chacun des codes déclarés coûte une poignée de requêtes ; parcourir tous les patients du bac
à sable en coûterait des centaines pour la même réponse.

La sonde n'émet que des `GET`, comme celle de conformité : elle interroge des bacs à sable
partagés, et une écriture accidentelle y abîmerait le travail d'autrui.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from passerelle.api.patients import PAR_IDENTIFIANT
from passerelle.fhir.client import ClientFhir, FhirIndisponible
from passerelle.fhir.contexte import contexte as assembler
from passerelle.requete.gabarits import apparier
from passerelle.requete.perimetre import PATHOLOGIES
from passerelle.sondes import sortie

#: Statuts cliniques qui valent « le problème est en cours ». Les mêmes que ceux du chemin
#: vif : un dossier retenu ici doit produire les requêtes annoncées.
ACTIFS = {"active", "recurrence", "relapse"}

#: Dossiers examinés en détail au plus. Chacun coûte deux lectures ; la sonde sert à trouver
#: un candidat, pas à inventorier le bac à sable.
PLAFOND = 12


def _porteurs(client: ClientFhir) -> dict[str, set[str]]:
    """Rend, par identifiant de patient, les pathologies dont il porte un code actif."""
    par_patient: dict[str, set[str]] = defaultdict(set)
    for patho in PATHOLOGIES:
        for declare in patho.codes:
            parametres = {"code": f"{patho.systeme}|{declare.code}"}
            try:
                trouvees = client.rechercher_conditions(parametres)
            except FhirIndisponible as erreur:
                print(f"{declare.code} : {erreur}", file=sys.stderr)
                continue
            for condition in trouvees:
                if _statut(condition) not in ACTIFS:
                    continue
                identifiant = _sujet(condition)
                if identifiant:
                    par_patient[identifiant].add(patho.identifiant)
            print(
                f"  {declare.code:>16s}  {len(trouvees)} conditions",
                file=sys.stderr,
            )
    return dict(par_patient)


def _statut(condition: dict) -> str:
    """Statut clinique d'une `Condition`, vide s'il n'est pas renseigné."""
    codes = (condition.get("clinicalStatus") or {}).get("coding") or []
    return str(codes[0].get("code", "")) if codes else ""


def _sujet(condition: dict) -> str:
    """Identifiant du patient référencé, vide si la référence est d'une autre forme."""
    reference = str((condition.get("subject") or {}).get("reference", ""))
    return reference.split("Patient/")[-1] if "Patient/" in reference else ""


def examiner(client: ClientFhir, identifiants: list[str]) -> list[dict[str, object]]:
    """Lit chaque dossier candidat et rend ce que la passerelle en tirerait réellement.

    L'appariement passe par `apparier`, qui applique les règles déclarées du périmètre : la
    recherche par code ne les connaît pas, et un candidat n'est retenu qu'une fois relu avec
    elles. Seules les conditions **actives** comptent.
    """
    dossiers: list[dict[str, object]] = []
    for identifiant in identifiants:
        try:
            contexte = assembler(client.patient(identifiant), client.conditions(identifiant))
        except FhirIndisponible as erreur:
            print(f"{identifiant} : {erreur}", file=sys.stderr)
            continue
        dossiers.append(
            {
                "identifiant": identifiant,
                "sexe": contexte.sexe or "",
                "age": contexte.age(),
                # Les patients de démonstration doivent être vivants : le premier retenu au
                # bloc 1 était mort en 1969.
                "vivant": contexte.deces is None,
                "conditions": len(contexte.problemes),
                "pathologies": sorted(apparier(contexte)),
                "deja_retenu": identifiant in PAR_IDENTIFIANT,
            }
        )
    return dossiers


def en_markdown(dossiers: list[dict[str, object]], minimum: int) -> str:
    """Rend le relevé en tableau collable."""
    lignes = [
        f"**Dossiers portant au moins {minimum} pathologies du périmètre**",
        "",
        "| identifiant | sexe | âge | vivant | conditions | pathologies | déjà retenu |",
        "| --- | --- | ---: | :---: | ---: | --- | :---: |",
    ]
    for dossier in dossiers:
        pathologies = dossier["pathologies"]
        lignes.append(
            f"| `{dossier['identifiant']}` | {dossier['sexe'] or '—'} "
            f"| {dossier['age'] if dossier['age'] is not None else '—'} "
            f"| {'oui' if dossier['vivant'] else '**non**'} | {dossier['conditions']} "
            f"| {', '.join(pathologies) or '—'} "  # type: ignore[arg-type]
            f"| {'oui' if dossier['deja_retenu'] else ''} |"
        )
    if not dossiers:
        lignes.append("| — | | | | | *aucun candidat* | |")
    lignes += [
        "",
        "Un candidat n'est utilisable que s'il est **vivant** et pas déjà dans la "
        "démonstration. La colonne « pathologies » est relue par `apparier`, qui applique le "
        "périmètre déclaré — la recherche par code, elle, l'ignore.",
    ]
    return "\n".join(lignes)


def main() -> int:
    """Point d'entrée `sonde-dossiers`."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "--minimum", type=int, default=2, help="pathologies du périmètre exigées"
    )
    analyseur.add_argument(
        "--plafond", type=int, default=PLAFOND, help="dossiers examinés en détail au plus"
    )
    sortie.declarer(analyseur)
    arguments = analyseur.parse_args()

    sortie.delier_de_la_console()
    client = ClientFhir()
    try:
        print("recherche par code…", file=sys.stderr)
        par_patient = _porteurs(client)
        candidats = [i for i, p in par_patient.items() if len(p) >= arguments.minimum]
        print(
            f"{len(par_patient)} porteurs, {len(candidats)} candidats — "
            f"{min(len(candidats), arguments.plafond)} examinés",
            file=sys.stderr,
        )
        dossiers = examiner(client, candidats[: arguments.plafond])
    finally:
        client.fermer()

    rendu = (
        json.dumps(dossiers, ensure_ascii=False, indent=2)
        if arguments.json
        else en_markdown(dossiers, arguments.minimum)
    )
    sortie.publier(rendu, arguments.sortie)

    # Aucun candidat n'est un résultat, pas une panne : le bac à sable peut n'en porter
    # aucun. Mais une recherche qui n'a joint personne, si.
    if not par_patient:
        print("aucun porteur trouvé — le serveur a-t-il répondu ?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
