"""Ce que le corpus de la HAS répond quand on lui demande de fonder le périmètre.

Deux codes avaient rejoint le périmètre de la BPCO sans autre justification que leur libellé
anglais, lu dans les données du bac à sable. Le guide de parcours ne les nommait pas.

Cette sonde a posé la question au seul juge que le projet reconnaisse : le corpus lui-même.
Aucun passage ne les rattachait à la maladie, et les deux ont été écartés — `ECARTES` du
périmètre porte le motif, `docs/perimetre.md` le raisonnement. La sonde reste : une nouvelle
archive du corpus, ou un guide actualisé, peuvent renverser le constat.
Elle rend les passages retrouvés, avec leur page et leur fiche HAS, **et ne conclut rien**.
La lecture et l'arbitrage reviennent à un humain : c'est la règle 5 de la conception, et
faire trancher le moteur ici la retournerait exactement.

Le critère est déclaré avant la mesure — champ `attendu` de chaque interrogation. Le décider
après avoir lu les passages reviendrait à choisir la preuve en fonction de la conclusion
souhaitée.

La rédaction du modèle n'est pas nécessaire : l'API rend les passages dans tous les cas, y
compris quand la synthèse manque faute de budget ou de fournisseur.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from pydantic import BaseModel, Field

from passerelle.documentaliste.client import Documentaliste
from passerelle.documentaliste.schemas import Passage, Reponse
from passerelle.sondes import sortie

#: Secondes entre deux interrogations. Le service limite à vingt appels par heure et par
#: adresse ; l'espacement ne sert pas à tenir ce plafond mais à ne pas rafaler un service
#: partagé pour trois questions.
ESPACEMENT = 1.2

#: Longueur d'extrait rendue par défaut. Un passage entier tient parfois sur une page ; la
#: sonde sert à juger, pas à recopier le corpus.
EXTRAIT = 700


class Interrogation(BaseModel):
    """Une question posée au corpus, et le code dont elle décide du sort."""

    intitule: str
    #: Code SNOMED en jeu. Vide pour la question d'ouverture, qui ne vise aucun code en
    #: particulier mais demande au corpus d'énumérer lui-même ce qu'il couvre.
    code: str = ""
    pathologie: str
    #: Ce qu'un passage devrait établir pour que le code tienne. **Déclaré avant la
    #: mesure.** Sans ce champ, tout passage vaguement pertinent finirait par convaincre.
    attendu: str


QUESTIONS: tuple[Interrogation, ...] = (
    Interrogation(
        intitule=(
            "quelles formes de bronchopneumopathie chronique obstructive la Haute Autorité "
            "de Santé décrit-elle ?"
        ),
        pathologie="bpco",
        attendu="une énumération des formes couvertes par le guide de parcours",
    ),
    Interrogation(
        intitule=(
            "la bronchite chronique obstructive est-elle une bronchopneumopathie chronique "
            "obstructive ?"
        ),
        code="185086009",
        pathologie="bpco",
        attendu="un passage rattachant la bronchite chronique obstructive à la BPCO",
    ),
    Interrogation(
        intitule=(
            "l'emphysème pulmonaire relève-t-il de la bronchopneumopathie chronique obstructive ?"
        ),
        code="87433001",
        pathologie="bpco",
        attendu="un passage rattachant l'emphysème pulmonaire à la BPCO",
    ),
)


class Observation(BaseModel):
    """Ce qu'une interrogation a rendu, sans interprétation."""

    interrogation: Interrogation
    #: « reponse », « constat_absence », « refus », ou « indéterminé » quand le service n'a
    #: pas répondu du tout. Un service injoignable ne prouve pas que le corpus est muet.
    issue: str
    #: Cause de dégradation rendue par le client. Vide quand l'appel a abouti et rédigé.
    cause: str = ""
    redaction_indisponible: bool = False
    refus: str = ""
    passages: list[Passage] = Field(default_factory=list)

    @property
    def mesuree(self) -> bool:
        """Vrai quand le corpus a été effectivement consulté.

        Des passages, même sans synthèse, constituent une mesure. Une absence de réponse du
        service n'en est pas une.
        """
        return self.issue != "indéterminé"


def _observer(interrogation: Interrogation, reponse: Reponse | None, cause: str) -> Observation:
    """Réduit une réponse à ce qui sert l'arbitrage, sans rien en déduire."""
    if reponse is None:
        return Observation(interrogation=interrogation, issue="indéterminé", cause=cause)
    return Observation(
        interrogation=interrogation,
        issue=reponse.issue,
        cause=cause,
        redaction_indisponible=reponse.redaction_indisponible,
        refus=reponse.refus,
        passages=reponse.passages,
    )


def interroger(
    questions: tuple[Interrogation, ...] = QUESTIONS,
    moteur: Documentaliste | None = None,
    espacement: float = ESPACEMENT,
) -> list[Observation]:
    """Pose chaque question au moteur documentaire et rend les observations.

    Aucun gabarit n'est passé au client : le repli sur les réponses enregistrées ferait lire
    des passages retrouvés pour une autre question, ce qui fonderait le périmètre sur une
    coïncidence.
    """
    documentaliste = moteur or Documentaliste()
    observations: list[Observation] = []
    try:
        for rang, question in enumerate(questions):
            if rang and espacement:
                time.sleep(espacement)
            reponse, cause = documentaliste.interroger(question.intitule)
            observation = _observer(question, reponse, cause)
            print(
                f"  {question.code or '—':>16s}  {observation.issue:16s} "
                f"{len(observation.passages)} passages",
                file=sys.stderr,
            )
            observations.append(observation)
    finally:
        if moteur is None:
            documentaliste.fermer()
    return observations


def _passage_en_markdown(passage: Passage, caracteres: int) -> list[str]:
    """Rend un passage avec de quoi le retrouver dans la publication d'origine."""
    texte = passage.texte.strip()
    if caracteres and len(texte) > caracteres:
        texte = texte[:caracteres].rstrip() + " […]"
    reference = f"{passage.titre or passage.document} — page {passage.page}"
    if passage.url:
        reference = f"[{reference}]({passage.url})"
    return [f"**[{passage.numero}]** {reference}", "", f"> {texte}", ""]


def en_markdown(observations: list[Observation], caracteres: int = EXTRAIT) -> str:
    """Rend le relevé en Markdown collable, passages compris."""
    lignes: list[str] = []
    for observation in observations:
        question = observation.interrogation
        en_jeu = f"`{question.code}`" if question.code else "aucun"
        lignes += [
            f"## {question.intitule}",
            "",
            f"- code en jeu : {en_jeu}",
            f"- attendu, déclaré avant la mesure : {question.attendu}",
            f"- issue : **{observation.issue}**",
        ]
        if observation.redaction_indisponible:
            lignes.append("- rédaction indisponible en amont — les passages restent probants")
        if observation.cause:
            lignes.append(f"- dégradation : {observation.cause}")
        if observation.refus:
            lignes.append(f"- motif du refus : {observation.refus}")
        lignes.append("")
        if not observation.passages:
            lignes += ["*Aucun passage retrouvé.*", ""]
            continue
        lignes.append(f"### {len(observation.passages)} passages retrouvés")
        lignes.append("")
        for passage in observation.passages:
            lignes += _passage_en_markdown(passage, caracteres)
    lignes += [
        "---",
        "",
        "La sonde ne conclut pas. Un code ne rejoint le périmètre que si un humain lit un "
        "passage qui satisfait l'attendu déclaré, et le cite en regard du code.",
    ]
    return "\n".join(lignes)


def main() -> int:
    """Point d'entrée `sonde-perimetre`."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "--caracteres",
        type=int,
        default=EXTRAIT,
        help="longueur d'extrait par passage ; 0 pour le texte entier",
    )
    sortie.declarer(analyseur)
    arguments = analyseur.parse_args()

    sortie.delier_de_la_console()
    print(f"{len(QUESTIONS)} interrogations…", file=sys.stderr)
    observations = interroger()
    print(file=sys.stderr)

    if arguments.json:
        rendu = json.dumps(
            [observation.model_dump() for observation in observations],
            ensure_ascii=False,
            indent=2,
        )
    else:
        rendu = en_markdown(observations, arguments.caracteres)
    sortie.publier(rendu, arguments.sortie)

    # Une sonde qui n'a rien mesuré ne doit pas rendre le même code qu'une sonde muette par
    # constat : sans cette distinction, un service injoignable passerait pour un corpus sans
    # réponse, et les deux codes sortiraient du périmètre pour une panne de réseau.
    if not any(observation.mesuree for observation in observations):
        print("aucune interrogation n'a abouti", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
