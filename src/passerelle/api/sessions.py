"""L'état d'un parcours d'autorisation, en mémoire et borné.

Rien n'est persisté : ni comptes, ni sessions durables. Au redémarrage, les autorisations en
cours tombent et la démonstration repasse en mode démonstration — une dégradation, pas une
panne.

Le nombre de sessions est borné pour la même raison que le registre des traces : un service
public qui tourne longtemps et n'oublie rien finit par manquer de mémoire.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from passerelle.smart.schemas import Demande, Jeton

#: Durée de vie d'une session, alignée sur celle d'un jeton SMART.
DUREE = timedelta(hours=1)

#: Nombre maximal de sessions simultanées.
PLAFOND = 200


class Session(BaseModel):
    """Un parcours d'autorisation, en cours ou abouti."""

    demande: Demande | None = None
    jeton: Jeton | None = None
    #: Base FHIR contre laquelle le parcours a été ouvert. Le retour et les consultations la
    #: relisent ici : le visiteur a pu choisir autre chose que le serveur par défaut, et
    #: retomber sur une variable globale lirait le dossier ailleurs qu'il ne l'a autorisé.
    base: str = ""
    expiration: datetime = Field(default_factory=lambda: datetime.now(UTC) + DUREE)

    @property
    def expiree(self) -> bool:
        return datetime.now(UTC) >= self.expiration

    @property
    def autorisee(self) -> bool:
        """Vrai si la session porte un jeton encore valable."""
        return self.jeton is not None and not self.expiree


class Sessions:
    """Les parcours en cours, indexés par un identifiant opaque."""

    def __init__(self, plafond: int = PLAFOND) -> None:
        self._sessions: dict[str, Session] = {}
        self._plafond = plafond

    def ouvrir(self, identifiant: str, demande: Demande, base: str = "") -> Session:
        """Ouvre une session pour un parcours d'autorisation contre une base donnée."""
        self._elaguer()
        session = Session(demande=demande, base=base)
        self._sessions[identifiant] = session
        return session

    def lire(self, identifiant: str | None) -> Session | None:
        """Rend la session, ou `None` si elle est absente ou expirée."""
        if not identifiant:
            return None
        session = self._sessions.get(identifiant)
        if session is None:
            return None
        if session.expiree:
            self._sessions.pop(identifiant, None)
            return None
        return session

    def deposer_jeton(self, identifiant: str, jeton: Jeton) -> None:
        """Attache un jeton à une session ouverte."""
        session = self._sessions.get(identifiant)
        if session is not None:
            session.jeton = jeton

    def _elaguer(self) -> None:
        """Retire les sessions expirées, puis les plus anciennes si le plafond est atteint."""
        for identifiant in [i for i, s in self._sessions.items() if s.expiree]:
            self._sessions.pop(identifiant, None)
        while len(self._sessions) >= self._plafond:
            self._sessions.pop(next(iter(self._sessions)))

    def __len__(self) -> int:
        return len(self._sessions)
