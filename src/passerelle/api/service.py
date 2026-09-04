"""L'orchestration d'une consultation, et le tissage du journal.

L'ordre des étapes porte une décision : **la lecture du dossier a lieu avant toute
considération de dégradation**. Un plafond atteint ou une clé absente ne doit jamais priver
d'un contexte qui a été lu — c'est la règle héritée du documentaliste, où la recherche
précède le contrôle de budget.

La résolution terminologique n'est pas encore branchée : elle consigne sa dégradation et
laisse les codes bruts. La trace le dit, plutôt que d'afficher un blanc.
"""

from __future__ import annotations

import logging
import os

from passerelle.api.patients import PAR_IDENTIFIANT
from passerelle.api.schemas import (
    Consultation,
    ConsultationRendue,
    DegradationRendue,
    ProblemeRendu,
    RequeteRendue,
)
from passerelle.documentaliste.client import Documentaliste
from passerelle.fhir.client import ClientFhir, FhirIndisponible
from passerelle.fhir.contexte import contexte as assembler
from passerelle.fhir.schemas import ContextePatient
from passerelle.journal.schemas import Frontiere, Mode, Trace
from passerelle.journal.tenue import Tenue
from passerelle.requete.gabarits import construire
from passerelle.requete.perimetre import pathologie
from passerelle.smart.schemas import Jeton

journal = logging.getLogger("passerelle.api")

TERMINOLOGIE_ABSENTE = "clé du Serveur Multi-Terminologies absente"
TERMINOLOGIE_CONSEQUENCE = "codes SNOMED affichés bruts, sans libellé français"


class PatientRefuse(PermissionError):
    """La passerelle refuse de lire ce patient."""


def cle_smt() -> str:
    """Clé d'API du Serveur Multi-Terminologies, lue dans l'environnement."""
    return os.environ.get("PASSERELLE_SMT_CLE", "").strip()


def _autoriser(demande: Consultation, jeton: Jeton | None, tenue: Tenue) -> None:
    """Contrôle que le patient demandé est bien celui que la passerelle s'autorise à lire.

    Le serveur amont **n'applique pas** les scopes qu'il accorde : mesuré, un jeton portant
    un contexte patient lit n'importe quel autre dossier. Ce contrôle est donc le seul qui
    ait lieu, et son refus n'a de trace nulle part ailleurs qu'ici.
    """
    if demande.mode is Mode.SMART:
        attendu = jeton.patient if jeton else None
        if not attendu:
            tenue.refus(demande.patient, "aucun contexte patient dans le jeton")
            raise PatientRefuse("aucun contexte patient dans le jeton")
        if demande.patient != attendu:
            tenue.refus(demande.patient, f"hors du contexte patient du jeton ({attendu})")
            raise PatientRefuse("patient hors du contexte du jeton")
        return

    if demande.patient not in PAR_IDENTIFIANT:
        tenue.refus(demande.patient, "hors de la liste des patients de démonstration")
        raise PatientRefuse("patient hors démonstration")


def _lire(demande: Consultation, jeton: Jeton | None, tenue: Tenue) -> ContextePatient:
    """Lit le dossier et consigne les deux accès avec leur frontière de confiance."""
    entetes = jeton.entete if (demande.mode is Mode.SMART and jeton) else None
    frontiere = Frontiere.DELEGUEE if entetes else Frontiere.AUCUNE
    autorisation = jeton.scope if (entetes and jeton) else ""

    client = ClientFhir()
    try:
        patient = client.patient(demande.patient)
        tenue.lecture(f"Patient/{demande.patient}", "serveur FHIR", frontiere, autorisation)
        conditions = client.conditions(demande.patient)
        tenue.lecture(
            f"Condition?patient={demande.patient}", "serveur FHIR", frontiere, autorisation
        )
    finally:
        client.fermer()
    return assembler(patient, conditions)


def _resoudre(contexte: ContextePatient, tenue: Tenue) -> list[ProblemeRendu]:
    """Rend les problèmes lus, résolus quand c'est possible.

    Sans clé du SMT, aucun libellé français n'est obtenu. La dégradation est consignée une
    fois, et chaque code non résolu l'est aussi : le taux de résolution reste calculable.
    """
    disponible = bool(cle_smt())
    if not disponible and contexte.problemes:
        tenue.degradation(TERMINOLOGIE_ABSENTE, TERMINOLOGIE_CONSEQUENCE)

    rendus: list[ProblemeRendu] = []
    for probleme in contexte.problemes:
        code = probleme.code
        dans_le_perimetre = pathologie(code.systeme, code.code) is not None
        tenue.probleme(
            systeme=code.systeme,
            code=code.code,
            libelle_source=code.libelle_source,
            libelle_fr=code.libelle_fr,
            terminologie="SNOMED CT",
            statut=probleme.statut,
            dans_le_perimetre=dans_le_perimetre,
        )
        rendus.append(
            ProblemeRendu(
                systeme=code.systeme,
                code=code.code,
                libelle_source=code.libelle_source,
                libelle_fr=code.libelle_fr,
                statut=probleme.statut,
                dans_le_perimetre=dans_le_perimetre,
            )
        )
    return rendus


def _interroger(contexte: ContextePatient, tenue: Tenue) -> list[RequeteRendue]:
    """Construit les questions et interroge le moteur documentaire pour chacune."""
    requetes = construire(contexte)
    if not requetes:
        journal.info("aucune pathologie du périmètre — aucune requête construite")
        return []

    moteur, rendues = Documentaliste(), []
    try:
        for requete in requetes:
            interrogation = tenue.interroger(requete.gabarit, requete.texte, requete.codes)
            tenue.lecture(
                "POST /question", "documentaliste", Frontiere.SERVICE, "appel serveur à serveur"
            )
            reponse, cause = moteur.interroger(requete.texte, requete.gabarit)
            if cause:
                tenue.degradation(cause, "réponse enregistrée servie à la place")
            if reponse is None:
                tenue.repondue(interrogation, "indisponible")
                rendues.append(
                    RequeteRendue(
                        gabarit=requete.gabarit,
                        texte=requete.texte,
                        codes=requete.codes,
                        issue="indisponible",
                        refus=cause,
                    )
                )
                continue
            tenue.repondue(
                interrogation,
                reponse.issue,
                reponse.origine,
                [defaut.motif for defaut in reponse.defauts],
            )
            for passage in reponse.passages:
                tenue.passage(
                    interrogation, passage.numero, passage.document, passage.page, passage.titre
                )
            rendues.append(
                RequeteRendue(
                    gabarit=requete.gabarit,
                    texte=requete.texte,
                    codes=requete.codes,
                    issue=reponse.issue,
                    refus=reponse.refus,
                    affirmations=reponse.affirmations,
                    passages=reponse.passages,
                    defauts=reponse.defauts,
                    origine=reponse.origine,
                )
            )
    finally:
        moteur.fermer()
    return rendues


def consulter(
    demande: Consultation, jeton: Jeton | None = None
) -> tuple[ConsultationRendue, Trace]:
    """Déroule une consultation et rend le résultat avec sa trace."""
    tenue = Tenue(mode=demande.mode, contexte_patient=demande.patient)
    if jeton is not None:
        tenue.autorise(jeton.scopes)

    _autoriser(demande, jeton, tenue)

    try:
        contexte = _lire(demande, jeton, tenue)
    except FhirIndisponible as erreur:
        tenue.degradation(f"serveur FHIR injoignable ({erreur})", "aucun dossier lu")
        trace = tenue.close()
        return _rendue(demande, None, [], [], trace), trace

    problemes = _resoudre(contexte, tenue)
    requetes = _interroger(contexte, tenue)
    trace = tenue.close()
    return _rendue(demande, contexte, problemes, requetes, trace), trace


def _rendue(
    demande: Consultation,
    contexte: ContextePatient | None,
    problemes: list[ProblemeRendu],
    requetes: list[RequeteRendue],
    trace: Trace,
) -> ConsultationRendue:
    """Assemble la réponse de l'API à partir de ce qui a été obtenu."""
    return ConsultationRendue(
        trace=trace.identifiant,
        patient=demande.patient,
        mode=demande.mode,
        sexe=contexte.sexe if contexte else None,
        age=contexte.age() if contexte else None,
        problemes=problemes,
        requetes=requetes,
        degradations=[
            DegradationRendue(cause=d.cause, consequence=d.consequence) for d in trace.degradations
        ],
    )
