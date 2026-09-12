"""Ce que les deux bacs à sable Oracle rendent possible, avant d'en dessiner le parcours.

Trois questions, qu'aucune documentation ne tranche et dont dépend le parcours proposé au
visiteur :

1. **quels dossiers le bac à sable ouvert expose-t-il**, et de quelle ampleur ? Chez Oracle,
   `Condition` exige `patient`, `subject` ou `_id` : la recherche par code de `sonde-dossiers`
   y est impossible, et la liste ne peut être que constituée dossier par dossier, à partir des
   patients de test que Cerner publie ;
2. **le bac à sable sécurisé délivre-t-il un jeton sans contexte patient** ? C'est la
   condition d'un parcours où c'est notre page, et non le serveur, qui présente la liste. Le
   jeu de portées s'éprouve avec `--portees` : c'est la variable de la mesure ;
3. **que ce jeton laisse-t-il lire** — le dossier désigné, ou rien ?

La troisième est la plus intéressante des trois. Le lanceur SMART, mesuré, n'applique pas les
portées qu'il accorde : un jeton portant un contexte patient y lit n'importe quel autre
dossier. Le bac à sable sécurisé est annoncé comme le seul à les appliquer. Cette sonde le
met à l'épreuve.

Elle n'émet que des `GET`, comme les autres : ces bacs à sable sont partagés, et une écriture
accidentelle y abîmerait le travail d'autrui.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from passerelle.api.serveurs import PAR_IDENTIFIANT as SERVEURS_PAR_ID
from passerelle.fhir.client import ClientFhir, FhirIndisponible
from passerelle.smart.autorisation import AutorisationRefusee
from passerelle.smart.decouverte import DecouverteImpossible
from passerelle.sondes import sortie
from passerelle.sondes.dossiers import examiner
from passerelle.sondes.parcours import autoriser

#: Portées éprouvées par défaut à la mesure 2.
#:
#: Le préfixe `user/` désigne ce que le praticien connecté a le droit de voir, sans référence
#: à un patient. `patient/`, lui, désigne le patient du contexte : il en suppose un.
PORTEES_DEFAUT = "user/Patient.read user/Condition.read openid fhirUser"


def lisibles(client: ClientFhir, identifiants: list[str]) -> list[dict[str, Any]]:
    """Ce que le serveur laisse lire de chaque dossier désigné.

    Le refus est un résultat au même titre que la lecture : c'est lui qui dirait que les
    portées sont appliquées. Il est donc consigné, jamais avalé.
    """
    releve: list[dict[str, Any]] = []
    for identifiant in identifiants:
        ligne: dict[str, Any] = {"identifiant": identifiant}
        try:
            client.patient(identifiant)
            ligne["patient"] = "lu"
        except FhirIndisponible as erreur:
            ligne["patient"] = f"refusé — {erreur}"
        try:
            ligne["conditions"] = len(client.conditions(identifiant))
        except FhirIndisponible as erreur:
            ligne["conditions"] = f"refusé — {erreur}"
        releve.append(ligne)
    return releve


def sans_autorisation(patients: list[str]) -> list[dict[str, object]]:
    """Mesure 1 — ce que le bac à sable ouvert rend sans le moindre jeton."""
    serveur = SERVEURS_PAR_ID["oracle_ouvert"]
    client = ClientFhir(serveur.base)
    try:
        return examiner(client, patients)
    finally:
        client.fermer()


def avec_jeton_sans_contexte(patients: list[str], portees: str = PORTEES_DEFAUT) -> dict[str, Any]:
    """Mesures 2 et 3 — le jeton obtenu sans contexte, et ce qu'il ouvre.

    Le parcours est interactif : l'opérateur suit l'adresse affichée, se connecte, puis
    recolle l'adresse de retour. Aucun service n'écoute la redirection.
    """
    serveur = SERVEURS_PAR_ID["oracle_securise"]
    jeton = autoriser(serveur.base, portees=portees)
    client = ClientFhir(serveur.base, entetes=jeton.entete)
    try:
        return {
            "portees_demandees": portees,
            "portees_accordees": jeton.scope,
            "contexte_patient": jeton.patient or "",
            "lectures": lisibles(client, patients),
        }
    finally:
        client.fermer()


def en_markdown(ouvert: list[dict[str, object]], securise: dict[str, Any] | None) -> str:
    """Rend le relevé en tableaux collables."""
    lignes = [
        "**Bac à sable ouvert — dossiers lus sans autorisation**",
        "",
        "| identifiant | sexe | âge | vivant | conditions |",
        "| --- | --- | ---: | :---: | ---: |",
    ]
    for dossier in ouvert:
        lignes.append(
            f"| `{dossier['identifiant']}` | {dossier['sexe'] or '—'} "
            f"| {dossier['age'] if dossier['age'] is not None else '—'} "
            f"| {'oui' if dossier['vivant'] else '**non**'} | {dossier['conditions']} |"
        )
    if not ouvert:
        lignes.append("| — | | | | *aucun dossier lu* |")

    if securise is None:
        lignes += ["", "*Bac à sable sécurisé : non mesuré — relancer avec `--autoriser`.*"]
        return "\n".join(lignes)

    lignes += [
        "",
        "**Bac à sable sécurisé — jeton demandé sans contexte patient**",
        "",
        f"- portées demandées : `{securise['portees_demandees']}`",
        f"- portées accordées : `{securise['portees_accordees'] or '—'}`",
        f"- contexte patient du jeton : `{securise['contexte_patient'] or 'aucun'}`",
        "",
        "| dossier désigné | `Patient` | `Condition` |",
        "| --- | --- | ---: |",
    ]
    for lecture in securise["lectures"]:
        lignes.append(
            f"| `{lecture['identifiant']}` | {lecture['patient']} | {lecture['conditions']} |"
        )
    lignes += [
        "",
        "Un jeton **sans contexte patient** qui lit malgré tout le dossier désigné rend "
        "possible un parcours où la page présente la liste. S'il refuse, le serveur applique "
        "ses portées — ce qui est la posture annoncée, et ferme cette voie.",
    ]
    return "\n".join(lignes)


def main() -> int:
    """Point d'entrée `sonde-oracle`."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "--patients",
        nargs="+",
        required=True,
        metavar="ID",
        help="identifiants de patients de test, tels que Cerner les publie",
    )
    analyseur.add_argument(
        "--autoriser",
        action="store_true",
        help="mène le parcours interactif sur le bac à sable sécurisé (mesures 2 et 3)",
    )
    analyseur.add_argument(
        "--portees",
        default=PORTEES_DEFAUT,
        metavar="LISTE",
        help="portées demandées au serveur d'autorisation, séparées par des espaces",
    )
    sortie.declarer(analyseur)
    arguments = analyseur.parse_args()

    sortie.delier_de_la_console()
    print(f"bac à sable ouvert — {len(arguments.patients)} dossiers…", file=sys.stderr)
    ouvert = sans_autorisation(arguments.patients)

    securise = None
    if arguments.autoriser:
        try:
            securise = avec_jeton_sans_contexte(arguments.patients, arguments.portees)
        except (AutorisationRefusee, DecouverteImpossible) as erreur:
            # Un refus est une mesure : il est consigné dans le relevé, pas seulement
            # imprimé, faute de quoi la moitié du travail serait perdue.
            print(f"parcours interrompu : {erreur}", file=sys.stderr)
            securise = {
                "portees_demandees": arguments.portees,
                "portees_accordees": f"refusé — {erreur}",
                "contexte_patient": "",
                "lectures": [],
            }

    rendu = (
        json.dumps({"ouvert": ouvert, "securise": securise}, ensure_ascii=False, indent=2)
        if arguments.json
        else en_markdown(ouvert, securise)
    )
    sortie.publier(rendu, arguments.sortie)

    # Aucun dossier lu sur un serveur sans autorisation n'est pas un résultat : c'est le
    # signe que les identifiants sont faux ou que le serveur n'a pas répondu.
    if not ouvert:
        print("aucun dossier lu — les identifiants sont-ils ceux du bac à sable ?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
