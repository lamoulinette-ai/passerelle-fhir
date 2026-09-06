"""Ce que le corpus rend sur une condition quelconque, désignée sans périmètre.

La conception change : la passerelle ne choisit plus quelles conditions méritent une
question. L'utilisateur en désigne une, la passerelle va chercher ce que la Haute Autorité
de Santé en dit. Il n'y a plus de sélection — donc plus rien à déclarer ni à fonder.

Reste une inconnue, et c'est elle qu'on mesure : **combien de conditions réelles obtiennent
quelque chose.** Le corpus couvre les maladies chroniques et les parcours de soins ; sur une
appendicite ou une pharyngite virale, il n'a probablement rien. Un système qui se tait neuf
fois sur dix est honnête et inutilisable, et il faut le savoir avant de construire la page.

**Ce que cette sonde ne mesure pas.** Le nombre de passages retrouvés est une constante :
la recherche rend toujours ses dix meilleurs, quelle que soit la question. Le compter revient
à compter dix. Seul le **verdict du juge** — répondre, constater une absence, ou refuser —
sépare une condition couverte d'une condition sur laquelle le corpus n'a rien.

Ce verdict exige le fournisseur du modèle, déjà coupé vingt-cinq heures. Quand il manque, la
colonne `rédaction` le dit et **la colonne `issue` ne veut plus rien dire** : tout devient un
refus, faute de juge. Un relevé pris dans cet état ne conclut pas.

Reste alors la seule lecture possible, et elle est humaine : le titre du premier document.
Il dit si la recherche a trouvé le bon guide ou le document le moins éloigné de rien.

Le service limite à vingt questions par heure et par adresse. Le plafond par défaut est
au-dessous, et l'augmenter fait dépasser.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from passerelle.api.patients import PATIENTS
from passerelle.documentaliste.client import Documentaliste
from passerelle.fhir.client import ClientFhir, FhirIndisponible
from passerelle.fhir.contexte import contexte as assembler
from passerelle.requete.gabarits import question_libre
from passerelle.requete.perimetre import pathologie
from passerelle.sondes import sortie
from passerelle.terminologie.client import Terminologie, TerminologieIndisponible

#: Secondes entre deux interrogations, comme sur le chemin vif.
ESPACEMENT = 1.2

#: Conditions interrogées au plus. Sous le plafond de vingt par heure du service.
PLAFOND = 15


def _conditions() -> list[dict[str, object]]:
    """Relève les conditions distinctes des dossiers de démonstration, libellé résolu.

    Une condition sans désignation française est retenue et signalée : poser une question en
    anglais à un corpus francophone est précisément ce que la mesure doit chiffrer, pas ce
    qu'elle doit éviter.
    """
    client, terminologie, vues = ClientFhir(), Terminologie(), {}
    try:
        for patient in PATIENTS:
            try:
                contexte = assembler(
                    client.patient(patient.identifiant), client.conditions(patient.identifiant)
                )
            except FhirIndisponible as erreur:
                print(f"{patient.identifiant} : {erreur}", file=sys.stderr)
                continue
            for probleme in contexte.problemes:
                code = probleme.code.code
                if code in vues:
                    continue
                try:
                    concept = terminologie.resoudre(probleme.code.systeme, code)
                    libelle, traduit = concept.libelle, concept.resolu
                except TerminologieIndisponible:
                    libelle, traduit = probleme.libelle or code, False
                vues[code] = {
                    "code": code,
                    "libelle": libelle,
                    "traduit": traduit,
                    "statut": probleme.statut,
                    "declare": pathologie(probleme.code.systeme, code) is not None,
                }
    finally:
        client.fermer()
        terminologie.fermer()
    return list(vues.values())


def interroger(
    conditions: list[dict[str, object]], espacement: float = ESPACEMENT
) -> list[dict[str, object]]:
    """Pose la question libre pour chaque condition et relève ce qui revient."""
    moteur, releves = Documentaliste(), []
    try:
        for rang, condition in enumerate(conditions):
            if rang and espacement:
                time.sleep(espacement)
            question = question_libre(str(condition["libelle"]))
            reponse, cause = moteur.interroger(question)
            passages = reponse.passages if reponse else []
            releve = {
                **condition,
                "question": question,
                "issue": reponse.issue if reponse else "indéterminé",
                "passages": len(passages),
                "premier": (passages[0].titre or passages[0].document) if passages else "",
                "redaction_indisponible": bool(reponse and reponse.redaction_indisponible),
                "cause": cause,
            }
            releves.append(releve)
            juge = "sans juge" if releve["redaction_indisponible"] else releve["issue"]
            print(
                f"  {str(condition['libelle'])[:38]:38s} {str(juge):16s} "
                f"{str(releve['premier'])[:40]}",
                file=sys.stderr,
            )
    finally:
        moteur.fermer()
    return releves


def en_markdown(releves: list[dict[str, object]]) -> str:
    """Rend le relevé en tableau collable, et dit ce qu'il ne permet pas de conclure."""
    sans_juge = [r for r in releves if r["redaction_indisponible"]]
    lignes = [
        "**Ce que le corpus rend sur une condition désignée, hors périmètre déclaré**",
        "",
        "| condition | déclarée | traduite | rédaction | issue | premier document |",
        "| --- | :---: | :---: | :---: | --- | --- |",
    ]
    for releve in releves:
        lignes.append(
            f"| {releve['libelle']} | {'oui' if releve['declare'] else ''} "
            f"| {'oui' if releve['traduit'] else '**non**'} "
            f"| {'**absente**' if releve['redaction_indisponible'] else 'oui'} "
            f"| {releve['issue']} | {str(releve['premier'])[:52]} |"
        )
    lignes.append("")
    if sans_juge:
        lignes += [
            f"⚠ **{len(sans_juge)} interrogations sur {len(releves)} sans rédaction.** "
            "Le juge était indisponible : la colonne « issue » ne dit alors rien de la "
            "couverture du corpus, seulement que le fournisseur du modèle était coupé. "
            "**Ce relevé ne tranche pas** — il faut le rejouer une fois le service revenu.",
            "",
        ]
    lignes += [
        "Le nombre de passages n'est pas rendu : la recherche en ramène toujours dix, quelle "
        "que soit la question. Le compter reviendrait à compter dix.",
        "",
        "La colonne qui se lit est **« premier document »**. Elle dit si la recherche a "
        "trouvé le guide de la condition demandée, ou le document le moins éloigné de rien.",
    ]
    return "\n".join(lignes)


def main() -> int:
    """Point d'entrée `sonde-libre`."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "--plafond", type=int, default=PLAFOND, help="conditions interrogées au plus"
    )
    analyseur.add_argument(
        "--declarees",
        action="store_true",
        help="n'interroger que les conditions du périmètre déclaré, pour comparer",
    )
    sortie.declarer(analyseur)
    arguments = analyseur.parse_args()

    sortie.delier_de_la_console()
    conditions = _conditions()
    if arguments.declarees:
        conditions = [c for c in conditions if c["declare"]]
    retenues = conditions[: arguments.plafond]
    print(
        f"{len(conditions)} conditions distinctes — {len(retenues)} interrogées",
        file=sys.stderr,
    )
    releves = interroger(retenues)

    rendu = (
        json.dumps(releves, ensure_ascii=False, indent=2)
        if arguments.json
        else en_markdown(releves)
    )
    sortie.publier(rendu, arguments.sortie)

    if not any(r["issue"] != "indéterminé" for r in releves):
        print("aucune interrogation n'a abouti", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
