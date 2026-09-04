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
from passerelle.api.schemas import Consultation, ConsultationRendue, Etat, Perimetre
from passerelle.api.service import PatientRefuse, cle_smt, consulter
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
limiteur = Limiter(key_func=get_remote_address, default_limits=_limites())


@asynccontextmanager
async def cycle(_app: FastAPI) -> AsyncIterator[None]:
    """Annonce au démarrage ce qui manque, plutôt que de le découvrir à la première requête."""
    journal.info("serveur FHIR : %s", fhir_base())
    journal.info("moteur documentaire : %s", documentaliste_api())
    journal.info("témoin de session Secure : %s", _temoin_sur())
    if not cle_smt():
        journal.warning("clé SMT absente — les codes seront affichés bruts")
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
    """Le processus répond, et l'état de ses deux dépendances."""
    terminologie = "disponible" if cle_smt() else "indisponible"
    return Etat(
        debout=True,
        complet=bool(cle_smt()),
        terminologie=terminologie,
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
        rendue, trace = consulter(demande, jeton)
    except PatientRefuse as refus:
        raise HTTPException(status_code=403, detail=str(refus)) from refus
    registre.deposer(trace)
    return rendue


@app.get("/smart/lancer")
def lancer(reponse: Response) -> RedirectResponse:
    """Ouvre un parcours d'autorisation SMART et pose le témoin de session."""
    try:
        configuration = decouvrir(fhir_base())
    except DecouverteImpossible as erreur:
        raise HTTPException(status_code=503, detail=str(erreur)) from erreur

    demande = demander(configuration, fhir_base(), _redirection())
    identifiant = secrets.token_urlsafe(24)
    sessions.ouvrir(identifiant, demande)
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
) -> dict[str, str]:
    """Reçoit le code d'autorisation et l'échange contre un jeton."""
    if error:
        raise HTTPException(status_code=400, detail=f"le serveur a refusé : {error}")
    session = sessions.lire(session_id)
    if session is None or session.demande is None:
        raise HTTPException(status_code=400, detail="aucun parcours d'autorisation en cours")
    try:
        configuration = decouvrir(fhir_base())
        jeton = echanger(configuration, session.demande, code, state, _redirection())
    except (AutorisationRefusee, DecouverteImpossible) as erreur:
        raise HTTPException(status_code=400, detail=str(erreur)) from erreur

    sessions.deposer_jeton(session_id or "", jeton)
    return {"contexte_patient": jeton.patient or "", "scopes": jeton.scope}


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
