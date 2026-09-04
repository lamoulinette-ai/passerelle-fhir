"""Enregistrement des réponses de secours, une par gabarit.

Les réponses de repli ne s'écrivent pas à la main : elles sont **prélevées** sur le service,
par cette commande, et régénérables à l'identique. Rédiger soi-même un passage attribué à la
Haute Autorité de Santé produirait exactement ce que ce projet s'emploie à rendre impossible.

Le contenu prélevé relève du corpus de la HAS, diffusé sous Licence Ouverte 2.0 : sa
présence dans le dépôt est permise, sous réserve d'attribution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from passerelle.documentaliste.client import ENREGISTREES, Documentaliste
from passerelle.requete.gabarits import FORME_DEFAUT, Forme, texte
from passerelle.requete.perimetre import PATHOLOGIES


def enregistrer(dossier: Path, forme: Forme = FORME_DEFAUT, refaire: bool = False) -> list[str]:
    """Interroge le service pour chaque gabarit et écrit les réponses. Rend les échecs.

    **Reprenable.** Les gabarits déjà enregistrés sont ignorés, sauf `refaire`. Le service
    limite les interrogations par adresse et par heure : sans reprise, un relevé interrompu
    aux deux tiers redemanderait les deux réponses déjà obtenues et buterait au même endroit.

    **Un refus ne s'enregistre pas.** Une réponse de secours qui refuse ferait refuser la
    démonstration en permanence dès la première indisponibilité du service — un défaut pire
    que l'absence de repli, et indiscernable d'un refus légitime.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    moteur, echecs = Documentaliste(), []
    try:
        for patho in PATHOLOGIES:
            if not refaire and (dossier / f"{patho.identifiant}.json").is_file():
                print(f"{patho.identifiant} : déjà enregistré, ignoré")
                continue
            question = texte(patho, forme)
            reponse, cause = moteur.interroger(question)
            if reponse is None or cause:
                echecs.append(f"{patho.identifiant} : {cause or 'aucune réponse'}")
                continue
            if reponse.issue == "refus":
                echecs.append(f"{patho.identifiant} : le service refuse — {reponse.refus[:120]}")
                continue
            if reponse.redaction_indisponible:
                echecs.append(f"{patho.identifiant} : rédaction coupée en amont, non enregistré")
                continue
            charge = reponse.model_dump(exclude={"origine"})
            fichier = dossier / f"{patho.identifiant}.json"
            fichier.write_text(json.dumps(charge, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{patho.identifiant} : {len(reponse.passages)} passages, issue {reponse.issue}")
    finally:
        moteur.fermer()
    return echecs


def main() -> int:
    """Point d'entrée `enregistrer-reponses`."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--dossier", type=Path, default=ENREGISTREES)
    analyseur.add_argument(
        "--refaire", action="store_true", help="réinterroger les gabarits déjà enregistrés"
    )
    arguments = analyseur.parse_args()

    echecs = enregistrer(arguments.dossier, refaire=arguments.refaire)
    for echec in echecs:
        print(f"échec — {echec}", file=sys.stderr)
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
