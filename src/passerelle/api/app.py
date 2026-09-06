"""Le service HTTP de la passerelle.

Deux règles d'architecture sont tenues ici :

- **la page n'appelle jamais un service extérieur elle-même** — ni le serveur FHIR, ni le
  documentaliste. Tout passe par ces routes, faute de quoi les appels n'apparaîtraient dans
  aucune trace et le journal mentirait par omission ;
- **une consultation rend toujours son identifiant de trace**, y compris quand elle échoue.
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from passerelle.api.patients import PATIENTS
from passerelle.api.schemas import (
    Consultation,
    ConsultationRendue,
    DegradationRendue,
    Etat,
    EtatSmart,
    Interrogation,
    InterrogationRendue,
    Perimetre,
    ServeurRendu,
)
from passerelle.api.serveurs import DEFAUT, SERVEURS
from passerelle.api.serveurs import PAR_IDENTIFIANT as SERVEURS_PAR_ID
from passerelle.api.service import (
    ConditionInconnue,
    PatientRefuse,
    consulter,
    interroger_condition,
    serveurs_joignables,
    terminologie_repond,
    terminologie_vue,
)
from passerelle.api.sessions import Sessions
from passerelle.documentaliste.client import api as documentaliste_api
from passerelle.fhir.client import base as fhir_base
from passerelle.journal.schemas import Trace
from passerelle.journal.tenue import Registre
from passerelle.requete.perimetre import PATHOLOGIES
from passerelle.smart.autorisation import AutorisationRefusee, demander, echanger
from passerelle.smart.decouverte import DecouverteImpossible, decouvrir

journal = logging.getLogger("passerelle")

TEMOIN = "passerelle_session"

AVERTISSEMENT = (
    "Démonstrateur technique sur données synthétiques. Outil de recherche documentaire : "
    "ne constitue ni un dispositif médical, ni un outil d'aide au diagnostic ou à la "
    "décision thérapeutique."
)

ORIGINES_DEFAUT = ("http://localhost:9000", "http://127.0.0.1:9000")


def charger_env(chemin: Path = Path(".env")) -> None:
    """Charge un fichier `.env` s'il existe, sans écraser l'environnement déjà posé."""
    if not chemin.is_file():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        nue = ligne.strip()
        if not nue or nue.startswith("#") or "=" not in nue:
            continue
        cle, _, valeur = nue.partition("=")
        os.environ.setdefault(cle.strip(), valeur.split("#")[0].strip())


charger_env()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")


def _origines() -> list[str]:
    """Origines autorisées, celles du développement à défaut."""
    brut = os.environ.get("CORS_ORIGINS", "").strip()
    if brut:
        return [origine.strip() for origine in brut.split(",") if origine.strip()]
    journal.warning("CORS_ORIGINS absent — repli sur %s", ", ".join(ORIGINES_DEFAUT))
    return list(ORIGINES_DEFAUT)


def _redirection() -> str:
    """Adresse de retour du parcours d'autorisation."""
    return os.environ.get("PASSERELLE_REDIRECTION", "http://localhost:8006/smart/retour").strip()


def _front() -> str:
    """Page qui reçoit le visiteur au retour du parcours d'autorisation.

    Lue dans l'environnement, jamais dans la requête : une adresse de retour qu'un paramètre
    pourrait choisir serait une redirection ouverte.
    """
    defaut = "http://localhost:9000/passerelle-fhir"
    return os.environ.get("PASSERELLE_FRONT", "").strip() or defaut


#: Motifs d'échec que la page peut recevoir. Vocabulaire fermé, et fermé pour une raison :
#: le serveur d'autorisation rend son propre texte d'erreur, et le recopier dans une adresse
#: que le navigateur affiche reviendrait à laisser un tiers écrire dans notre interface.
MOTIFS = frozenset({"refus", "sans_parcours", "echange"})


def _retour_au_front(motif: str = "") -> RedirectResponse:
    """Ramène le visiteur sur la page, avec l'issue du parcours.

    Le motif doit être déclaré : un motif inconnu est une faute de programmation, et la
    laisser passer rouvrirait le chemin par lequel un texte étranger atteindrait l'adresse.
    """
    if motif and motif not in MOTIFS:
        raise ValueError(f"motif non déclaré : {motif}")
    issue = f"smart=echec&motif={motif}" if motif else "smart=ok"
    separateur = "&" if "?" in _front() else "?"
    return RedirectResponse(f"{_front()}{separateur}{issue}", status_code=302)


def _temoin_sur() -> bool:
    """Vrai si le témoin de session doit porter l'attribut `Secure`.

    Déduit de l'adresse de retour plutôt que déclaré à part : les deux réglages décrivent la
    même chose — le service est-il derrière TLS — et une variable supplémentaire finirait par
    diverger de l'autre sans que rien ne le signale.
    """
    return _redirection().lower().startswith("https://")


def _limites() -> list[str]:
    """Limites de débit, désactivables — la suite de tests en émet plus qu'un visiteur."""
    if os.environ.get("RATELIMIT_ENABLED", "true").strip().lower() in {"false", "0", "non"}:
        return []
    return [os.environ.get("RATELIMIT", "60/hour").strip() or "60/hour"]


registre = Registre()
sessions = Sessions()

#: Serveurs dont la configuration SMART a répondu au démarrage, par identifiant. Vide tant
#: que le service n'a pas démarré, ce qui rend tout injoignable — et donc la démonstration
#: dégradée. C'est le bon sens du défaut : ne proposer une connexion qu'après l'avoir éprouvée.
joignables: dict[str, bool] = {}

limiteur = Limiter(key_func=get_remote_address, default_limits=_limites())


def _degradee() -> bool:
    """Vrai quand aucun serveur ouvert au public n'a répondu au démarrage.

    Seuls les serveurs ouverts au public comptent : les deux bacs à sable Oracle exigent des
    identifiants personnels, et leur disponibilité ne change rien à ce qu'un visiteur peut
    faire. Les compter ferait passer pour utilisable une démonstration qui ne l'est pas.
    """
    return not any(joignables.get(s.identifiant, False) for s in SERVEURS if s.ouvert_au_public)


@asynccontextmanager
async def cycle(_app: FastAPI) -> AsyncIterator[None]:
    """Annonce au démarrage ce qui manque, plutôt que de le découvrir à la première requête."""
    journal.info("serveur FHIR : %s", fhir_base())
    journal.info("moteur documentaire : %s", documentaliste_api())
    journal.info("témoin de session Secure : %s", _temoin_sur())
    # Première observation. Chaque consultation la révisera ensuite : un drapeau mesuré une
    # seule fois resterait faux longtemps après le retour du service.
    temoin = terminologie_repond()
    if temoin:
        journal.info("terminologie disponible — concept témoin : « %s »", temoin)
    else:
        journal.warning("terminologie injoignable — les codes seront affichés bruts")
    joignables.update(serveurs_joignables())
    if _degradee():
        journal.warning(
            "aucun serveur ouvert au public ne répond — la démonstration servira les dossiers "
            "enregistrés"
        )
    yield


app = FastAPI(title="Passerelle FHIR", lifespan=cycle)
app.state.limiter = limiteur
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origines(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Etat:
    """Le processus répond, et l'état de ses deux dépendances.

    L'état de la terminologie est celui de la **dernière résolution réelle**, pas celui du
    démarrage : c'est le chemin vif qui le révise, sans requête supplémentaire.
    """
    temoin, vue = terminologie_vue()
    disponible = bool(temoin)
    return Etat(
        debout=True,
        complet=disponible,
        terminologie="disponible" if disponible else "injoignable",
        terminologie_vue=vue,
        moteur_documentaire=documentaliste_api(),
        serveur_fhir=fhir_base(),
        traces=len(registre),
    )


@app.get("/perimetre")
def perimetre() -> Perimetre:
    """Ce que la démonstration couvre, pour que la page n'ait rien à coder en dur."""
    return Perimetre(
        pathologies=[patho.libelle for patho in PATHOLOGIES],
        patients=[
            {"identifiant": p.identifiant, "libelle": p.libelle, "illustre": p.illustre}
            for p in PATIENTS
        ],
        serveurs=[
            ServeurRendu(
                identifiant=serveur.identifiant,
                libelle=serveur.libelle,
                posture=serveur.posture,
                ouvert_au_public=serveur.ouvert_au_public,
                reserve=serveur.reserve,
                joignable=joignables.get(serveur.identifiant, False),
            )
            for serveur in SERVEURS
        ],
        degradee=_degradee(),
        corpus="archive HAS du 18 juin 2026",
        avertissement=AVERTISSEMENT,
    )


@app.post("/consulter")
def consultation(
    demande: Consultation,
    session_id: str | None = Cookie(default=None, alias=TEMOIN),
) -> ConsultationRendue:
    """Lit un dossier, construit les questions, interroge le corpus, et trace le tout."""
    session = sessions.lire(session_id)
    jeton = session.jeton if session and session.autorisee else None
    try:
        rendue, trace = consulter(demande, jeton, base=session.base if session else "")
    except PatientRefuse as refus:
        raise HTTPException(status_code=403, detail=str(refus)) from refus
    registre.deposer(trace)
    return rendue


@app.post("/interroger")
def interrogation(demande: Interrogation) -> InterrogationRendue:
    """Pose au corpus la question d'une condition que l'utilisateur a désignée.

    La trace fait office d'autorisation : le code doit figurer parmi les problèmes qu'elle a
    consignés. Sans cette contrainte, la route serait une recherche libre sur le corpus, et
    la question ne viendrait plus d'un dossier lu — ce que le journal est censé raconter.
    """
    trace = registre.par_identifiant(demande.trace)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace inconnue ou sortie de la mémoire")
    try:
        requete = interroger_condition(trace, demande.code)
    except ConditionInconnue as erreur:
        raise HTTPException(status_code=400, detail=str(erreur)) from erreur
    return InterrogationRendue(
        trace=trace.identifiant,
        requete=requete,
        degradations=[
            DegradationRendue(cause=d.cause, consequence=d.consequence) for d in trace.degradations
        ],
    )


@app.get("/smart/lancer")
def lancer(reponse: Response, serveur: str = "") -> RedirectResponse:
    """Ouvre un parcours d'autorisation SMART et pose le témoin de session.

    Le serveur est désigné par son **identifiant déclaré**, jamais par son adresse : accepter
    une base arbitraire en paramètre laisserait n'importe qui faire interroger n'importe
    quelle adresse par la passerelle.
    """
    retenu = SERVEURS_PAR_ID.get(serveur, DEFAUT) if serveur else DEFAUT
    if serveur and serveur not in SERVEURS_PAR_ID:
        raise HTTPException(status_code=400, detail=f"serveur inconnu : {serveur}")
    try:
        configuration = decouvrir(retenu.base)
    except DecouverteImpossible as erreur:
        raise HTTPException(status_code=503, detail=str(erreur)) from erreur

    demande = demander(configuration, retenu.base, _redirection())
    identifiant = secrets.token_urlsafe(24)
    sessions.ouvrir(identifiant, demande, base=retenu.base)
    redirection = RedirectResponse(demande.url, status_code=302)
    redirection.set_cookie(
        TEMOIN,
        identifiant,
        httponly=True,
        secure=_temoin_sur(),
        samesite="lax",
        max_age=3600,
        path="/",
    )
    return redirection


@app.get("/smart/retour")
def retour(
    code: str = "",
    state: str = "",
    error: str = "",
    session_id: str | None = Cookie(default=None, alias=TEMOIN),
) -> RedirectResponse:
    """Reçoit le code d'autorisation, l'échange, et renvoie le visiteur sur la page.

    Cette route est atteinte par une **navigation du navigateur**, pas par un appel de la
    page : rendre du JSON y laisserait le visiteur devant une accolade. Elle redirige donc
    dans tous les cas, succès comme échec, et c'est `/smart/etat` que la page interroge
    ensuite pour savoir ce qui s'est passé.

    Le jeton ne traverse jamais le navigateur. Il est déposé dans la session, que seul le
    témoin `httponly` désigne.
    """
    if error:
        journal.warning("parcours refusé par le serveur d'autorisation : %s", error[:200])
        return _retour_au_front("refus")

    session = sessions.lire(session_id)
    if session is None or session.demande is None:
        journal.warning("retour sans parcours en cours — témoin absent ou session expirée")
        return _retour_au_front("sans_parcours")

    base = session.base or fhir_base()
    try:
        configuration = decouvrir(base)
        jeton = echanger(configuration, session.demande, code, state, _redirection())
    except (AutorisationRefusee, DecouverteImpossible) as erreur:
        journal.warning("échange du code impossible : %s", erreur)
        return _retour_au_front("echange")

    sessions.deposer_jeton(session_id or "", jeton)
    journal.info("parcours abouti — contexte patient : %s", jeton.patient or "aucun")
    return _retour_au_front()


@app.get("/smart/etat")
def etat_smart(session_id: str | None = Cookie(default=None, alias=TEMOIN)) -> EtatSmart:
    """Ce que la page peut savoir du parcours en cours — jamais le jeton."""
    session = sessions.lire(session_id)
    if session is None or not session.autorisee or session.jeton is None:
        return EtatSmart(serveur=DEFAUT.base, serveur_identifiant=DEFAUT.identifiant)
    base = session.base or fhir_base()
    declare = next((serveur for serveur in SERVEURS if serveur.base == base), None)
    return EtatSmart(
        autorisee=True,
        contexte_patient=session.jeton.patient or "",
        scopes=session.jeton.scope,
        serveur=base,
        serveur_identifiant=declare.identifiant if declare else "",
    )


@app.get("/journal")
def dernieres(combien: int = 10) -> list[Trace]:
    """Les dernières traces, les plus récentes d'abord."""
    return registre.dernieres(min(max(combien, 1), 50))


@app.get("/journal/{identifiant}")
def trace(identifiant: str) -> Trace:
    """Une trace, par son identifiant."""
    trouvee = registre.par_identifiant(identifiant)
    if trouvee is None:
        raise HTTPException(status_code=404, detail="trace inconnue ou sortie de la mémoire")
    return trouvee


@app.exception_handler(Exception)
async def imprevu(_requete: Request, erreur: Exception) -> Response:
    """Aucune trace de pile ne sort du service ; le journal, lui, garde tout."""
    reference = uuid.uuid4().hex[:8]
    journal.exception("incident %s", reference)
    return Response(
        content=f'{{"detail":"incident {reference}"}}',
        status_code=503,
        media_type="application/json",
    )
