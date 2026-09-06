"""L'orchestration d'une consultation, et le tissage du journal.

Deux gestes, et non un seul : **lire un dossier** et **interroger le corpus** sur une de ses
conditions. La passerelle ne décide plus de ce qui mérite d'être demandé — elle rend ce
qu'elle a lu, et l'utilisateur désigne. Les deux gestes s'inscrivent dans la **même trace**,
sans quoi le lien entre la lecture et la question qu'elle a permise serait perdu.

L'ordre des étapes porte une décision : **la lecture du dossier a lieu avant toute
considération de dégradation**. Un plafond atteint ou une clé absente ne doit jamais priver
d'un contexte qui a été lu — c'est la règle héritée du documentaliste, où la recherche
précède le contrôle de budget.

Quand le serveur de terminologies ne répond pas, les codes restent bruts et la trace le dit,
plutôt que d'afficher un blanc.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx

from passerelle.api.patients import PAR_IDENTIFIANT
from passerelle.api.schemas import (
    Consultation,
    ConsultationRendue,
    DegradationRendue,
    ProblemeRendu,
    RequeteRendue,
)
from passerelle.api.serveurs import SERVEURS, ServeurFhir
from passerelle.documentaliste.client import Documentaliste
from passerelle.documentaliste.schemas import Reponse
from passerelle.fhir.client import ClientFhir, FhirIndisponible
from passerelle.fhir.contexte import contexte as assembler
from passerelle.fhir.schemas import ContextePatient
from passerelle.journal.schemas import Frontiere, Mode, ProblemeObserve, Trace
from passerelle.journal.tenue import Tenue
from passerelle.requete.gabarits import FORME_DEFAUT, question_libre
from passerelle.requete.gabarits import texte as texte_gabarit
from passerelle.requete.perimetre import pathologie
from passerelle.smart.decouverte import DecouverteImpossible, decouvrir
from passerelle.smart.schemas import Jeton
from passerelle.terminologie.client import Terminologie, TerminologieIndisponible

journal = logging.getLogger("passerelle.api")

TERMINOLOGIE_CONSEQUENCE = "codes SNOMED affichés bruts, sans libellé français"

#: Concept servant à éprouver le serveur de terminologies au démarrage. Le diabète de type 2
#: est dans le périmètre, traduit, et stable depuis 2002.
CONCEPT_TEMOIN = ("http://snomed.info/sct", "44054006")


class PatientRefuse(PermissionError):
    """La passerelle refuse de lire ce patient."""


#: Ce que la **dernière résolution réelle** a montré, et quand.
#:
#: Le démarrage y écrit sa sonde, puis chaque consultation la révise. Un drapeau mesuré une
#: seule fois ment par immobilité : une indisponibilité de trente secondes au démarrage le
#: figeait à « injoignable » pendant des jours, alors que le service résolvait correctement à
#: chaque requête — constaté en production.
#:
#: Révisé par le chemin vif plutôt que par une nouvelle sonde : la résolution a déjà lieu,
#: elle dit la vérité sur le service tel qu'il est employé, et elle n'ajoute aucune requête.
#: Sonder à chaque appel de `/health` en ferait deux par minute pour un drapeau.
_TERMINOLOGIE: dict[str, str] = {"temoin": "", "vue": ""}


def _noter_terminologie(temoin: str) -> None:
    """Retient ce que la terminologie vient de montrer, et l'instant de l'observation."""
    _TERMINOLOGIE["temoin"] = temoin
    _TERMINOLOGIE["vue"] = datetime.now(UTC).isoformat(timespec="seconds")


def terminologie_vue() -> tuple[str, str]:
    """Rend `(témoin, horodatage)` de la dernière observation. Vides avant la première.

    L'horodatage est rendu pour que `/health` ne se contente pas d'affirmer : un « disponible »
    observé il y a trois jours et un observé il y a dix secondes ne disent pas la même chose,
    et le lecteur doit pouvoir faire la différence lui-même.
    """
    return _TERMINOLOGIE["temoin"], _TERMINOLOGIE["vue"]


def terminologie_repond() -> str:
    """Éprouve le serveur de terminologies sur un concept témoin, au démarrage.

    Rend le libellé obtenu, ou une chaîne vide, et le note comme première observation.
    """
    terminologie = Terminologie()
    try:
        temoin = terminologie.resoudre(*CONCEPT_TEMOIN).libelle_fr or ""
    except TerminologieIndisponible as erreur:
        journal.warning("terminologie injoignable au démarrage : %s", erreur)
        temoin = ""
    finally:
        terminologie.fermer()
    _noter_terminologie(temoin)
    return temoin


#: Délai de la sonde de démarrage, en secondes. Plus court que celui d'une lecture réelle.
#:
#: `/health` ne répond pas tant que le démarrage n'est pas fini, et le script de déploiement
#: revient à l'image précédente au bout de trente secondes. Trois bacs à sable publics lents
#: suffiraient à faire échouer un déploiement sain. Cinq secondes suffisent d'ailleurs à la
#: question posée : un serveur qui met plus longtemps à publier sa configuration n'est pas
#: utilisable pour une démonstration.
DELAI_SONDE = 5.0


def serveurs_joignables() -> dict[str, bool]:
    """Éprouve la configuration SMART de chaque serveur déclaré, en parallèle.

    Appelé **une fois au démarrage**. La page a besoin de savoir si une connexion est
    possible avant d'en proposer une : présenter trois boutons dont aucun n'aboutit fait
    porter à l'utilisateur le diagnostic d'une panne que le service connaissait déjà.

    Un serveur qui ne publie pas sa configuration est déclaré injoignable. C'est plus sévère
    que « ne répond pas » — un serveur debout mais sans point d'entrée d'autorisation ne
    permet pas davantage de se connecter.
    """

    def eprouver(serveur: ServeurFhir) -> tuple[str, bool]:
        try:
            with httpx.Client(timeout=DELAI_SONDE) as client:
                decouvrir(serveur.base, client)
        except DecouverteImpossible as erreur:
            journal.warning("%s injoignable : %s", serveur.identifiant, erreur)
            return serveur.identifiant, False
        return serveur.identifiant, True

    with ThreadPoolExecutor(max_workers=len(SERVEURS)) as pool:
        return dict(pool.map(eprouver, SERVEURS))


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


def _lire(
    demande: Consultation, jeton: Jeton | None, tenue: Tenue, base: str = ""
) -> ContextePatient:
    """Lit le dossier et consigne les deux accès avec leur frontière de confiance."""
    entetes = jeton.entete if (demande.mode is Mode.SMART and jeton) else None
    frontiere = Frontiere.DELEGUEE if entetes else Frontiere.AUCUNE
    autorisation = jeton.scope if (entetes and jeton) else ""

    client = ClientFhir(adresse=base or None)
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
    """Résout les codes en français et rattache ceux dont un parent est au périmètre.

    Une seule dégradation est consignée si le serveur de terminologies ne répond pas : les
    codes restent bruts, et chaque problème est rendu tel qu'il a été lu.
    """
    terminologie, panne, temoin = Terminologie(), "", ""
    rendus: list[ProblemeRendu] = []
    try:
        for probleme in contexte.problemes:
            code = probleme.code
            concept = None
            if not panne:
                try:
                    concept = terminologie.resoudre(code.systeme, code.code)
                    temoin = temoin or concept.libelle_fr or concept.display or code.code
                except TerminologieIndisponible as erreur:
                    panne = f"serveur de terminologies injoignable ({erreur})"
                    journal.warning("%s", panne)

            trouvee = pathologie(code.systeme, code.code)
            tenue.probleme(
                systeme=code.systeme,
                code=code.code,
                libelle_source=code.libelle_source,
                libelle_fr=concept.libelle_fr if concept else None,
                terminologie=concept.terminologie if concept else "",
                version=concept.version if concept else "",
                statut=probleme.statut,
                dans_le_perimetre=trouvee is not None,
            )
            rendus.append(
                ProblemeRendu(
                    systeme=code.systeme,
                    code=code.code,
                    libelle_source=code.libelle_source,
                    libelle_fr=concept.libelle_fr if concept else None,
                    statut=probleme.statut,
                    dans_le_perimetre=trouvee is not None,
                )
            )
    finally:
        terminologie.fermer()

    if panne and contexte.problemes:
        tenue.degradation(panne, TERMINOLOGIE_CONSEQUENCE)

    # Un dossier sans problème codé n'apprend rien sur la terminologie : rien n'a été demandé,
    # et noter « injoignable » sur ce silence effacerait une observation valide.
    if contexte.problemes:
        _noter_terminologie("" if panne else temoin)
    return rendus


class ConditionInconnue(LookupError):
    """Le code demandé ne figure pas parmi les problèmes lus dans ce dossier."""


#: Réponses déjà obtenues, indexées par le texte de la question.
#:
#: Le corpus ne change pas entre deux visiteurs : « que publie la Haute Autorité de Santé
#: sur : diabète de type 2 ? » a la même réponse pour tout le monde. Sans ce cache, une
#: démonstration publique épuiserait en trois minutes les vingt questions par heure que le
#: moteur documentaire accorde par adresse — et la passerelle l'appelle depuis une seule.
CACHE: OrderedDict[str, Reponse] = OrderedDict()

#: Questions gardées en mémoire. Une réponse pèse ses dix passages.
MEMOIRE_CACHE = 256


def _cachee(question: str) -> Reponse | None:
    """Rend la réponse déjà obtenue pour cette question, ou `None`."""
    if question not in CACHE:
        return None
    CACHE.move_to_end(question)
    return CACHE[question]


def _cacher(question: str, reponse: Reponse) -> None:
    """Retient une réponse obtenue du service, jamais une réponse dégradée.

    Servir plus tard un repli qui n'était dû qu'à une panne passagère du fournisseur figerait
    l'indisponibilité bien après sa fin — et la démonstration continuerait de montrer une
    réponse enregistrée alors que le moteur est revenu.
    """
    if reponse.redaction_indisponible or reponse.origine != "service":
        return
    CACHE[question] = reponse
    while len(CACHE) > MEMOIRE_CACHE:
        CACHE.popitem(last=False)


def question_pour(probleme: ProblemeObserve) -> tuple[str, str, str]:
    """Rend `(gabarit, texte, libellé)` pour une condition désignée par l'utilisateur.

    Les codes du périmètre gardent la formulation **mesurée** et leur réponse enregistrée en
    repli ; les autres partent sur la forme libre, qui n'a besoin d'aucun article. Le
    périmètre ne filtre plus rien : il distingue les questions préparées des autres.
    """
    libelle = probleme.libelle_fr or probleme.libelle_source or probleme.code
    patho = pathologie(probleme.systeme, probleme.code)
    if patho is not None:
        return patho.identifiant, texte_gabarit(patho, FORME_DEFAUT), patho.libelle
    return "", question_libre(libelle), libelle


def interroger_condition(trace: Trace, code: str) -> RequeteRendue:
    """Pose au corpus la question d'une condition **désignée par l'utilisateur**.

    Le code doit figurer parmi les problèmes de cette trace. Accepter un code quelconque
    ferait de la passerelle un moteur de recherche libre sur le corpus, et la question ne
    viendrait plus d'un dossier lu — ce qui est tout ce que la traçabilité raconte.
    """
    probleme = next((p for p in trace.problemes if p.code == code), None)
    if probleme is None:
        raise ConditionInconnue(f"condition absente du dossier : {code}")

    tenue = Tenue.reprendre(trace)
    gabarit, texte, libelle = question_pour(probleme)
    interrogation = tenue.interroger(gabarit or code, texte, [code])

    if not probleme.libelle_fr:
        tenue.degradation(
            f"« {libelle} » sans désignation française",
            "question posée dans la langue du serveur à un corpus francophone",
        )

    reponse, cause = _obtenir(texte, gabarit, tenue)
    if reponse is None:
        tenue.repondue(interrogation, "indisponible")
        return RequeteRendue(
            gabarit=gabarit or code, texte=texte, codes=[code], issue="indisponible", refus=cause
        )

    tenue.repondue(
        interrogation,
        reponse.issue,
        reponse.origine,
        [defaut.motif for defaut in reponse.defauts],
        reponse.redaction_indisponible,
    )
    for passage in reponse.passages:
        tenue.passage(interrogation, passage.numero, passage.document, passage.page, passage.titre)
    return RequeteRendue(
        gabarit=gabarit or code,
        texte=texte,
        codes=[code],
        issue=reponse.issue,
        refus=reponse.refus,
        affirmations=reponse.affirmations,
        passages=reponse.passages,
        defauts=reponse.defauts,
        origine=reponse.origine,
        redaction_indisponible=reponse.redaction_indisponible,
    )


def _obtenir(texte: str, gabarit: str, tenue: Tenue) -> tuple[Reponse | None, str]:
    """Rend la réponse à une question, du cache ou du moteur, et consigne la lecture."""
    deja = _cachee(texte)
    if deja is not None:
        tenue.lecture("question déjà posée", "cache", Frontiere.AUCUNE, statut="servie du cache")
        return deja, ""

    moteur = Documentaliste()
    try:
        tenue.lecture(
            "POST /question", "documentaliste", Frontiere.SERVICE, "appel serveur à serveur"
        )
        reponse, cause = moteur.interroger(texte, gabarit)
    finally:
        moteur.fermer()
    if cause:
        tenue.degradation(cause, "réponse enregistrée servie à la place")
    if reponse is not None:
        _cacher(texte, reponse)
    return reponse, cause


def consulter(
    demande: Consultation, jeton: Jeton | None = None, base: str = ""
) -> tuple[ConsultationRendue, Trace]:
    """Déroule une consultation et rend le résultat avec sa trace."""
    tenue = Tenue(mode=demande.mode, contexte_patient=demande.patient)
    if jeton is not None:
        tenue.autorise(jeton.scopes)

    _autoriser(demande, jeton, tenue)

    try:
        contexte = _lire(demande, jeton, tenue, base)
    except FhirIndisponible as erreur:
        tenue.degradation(f"serveur FHIR injoignable ({erreur})", "aucun dossier lu")
        trace = tenue.close()
        return _rendue(demande, None, [], trace), trace

    problemes = _resoudre(contexte, tenue)
    trace = tenue.close()
    # Aucune question n'est posée ici : c'est l'utilisateur qui désignera une condition.
    # La passerelle ne choisit plus ce qui mérite d'être demandé.
    return _rendue(demande, contexte, problemes, trace), trace


def _rendue(
    demande: Consultation,
    contexte: ContextePatient | None,
    problemes: list[ProblemeRendu],
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
        degradations=[
            DegradationRendue(cause=d.cause, consequence=d.consequence) for d in trace.degradations
        ],
    )
