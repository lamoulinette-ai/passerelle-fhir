"""Tenue du journal : assemblage d'une trace, et registre des dernières.

Rien n'est écrit sur disque. Le conteneur tourne en lecture seule, et un journal qui
exigerait un volume inscriptible se paierait en incident au déploiement plutôt qu'en
information.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from collections.abc import Iterator

from passerelle.journal.schemas import (
    Acces,
    Decision,
    Degradation,
    Frontiere,
    Interrogation,
    Mode,
    PassageCite,
    ProblemeObserve,
    Trace,
)

#: Nombre de traces conservées. Au-delà, les plus anciennes sortent.
MEMOIRE = 50


class Tenue:
    """Assemble la trace d'une requête, section par section."""

    def __init__(self, mode: Mode = Mode.DEMONSTRATION, contexte_patient: str = "") -> None:
        self.trace = Trace(
            identifiant=uuid.uuid4().hex,
            mode=mode,
            contexte_patient=contexte_patient,
        )

    def autorise(self, scopes: list[str]) -> None:
        """Consigne les scopes réellement accordés, qui peuvent différer des demandés."""
        self.trace.scopes_accordes = list(scopes)

    def lecture(
        self,
        ressource: str,
        origine: str,
        frontiere: Frontiere,
        autorisation: str = "",
        statut: str = "obtenu",
    ) -> None:
        """Consigne une lecture vers un service extérieur."""
        self.trace.acces.append(
            Acces(
                ressource=ressource,
                origine=origine,
                frontiere=frontiere,
                autorisation=autorisation,
                statut=statut,
            )
        )

    def probleme(
        self,
        systeme: str,
        code: str,
        libelle_source: str = "",
        libelle_fr: str | None = None,
        terminologie: str = "",
        version: str = "",
        statut: str = "",
        dans_le_perimetre: bool = False,
    ) -> None:
        """Consigne un problème lu, sa résolution tentée, et son appartenance au périmètre."""
        self.trace.problemes.append(
            ProblemeObserve(
                systeme=systeme,
                code=code,
                libelle_source=libelle_source,
                libelle_fr=libelle_fr,
                terminologie=terminologie,
                version=version,
                statut=statut,
                dans_le_perimetre=dans_le_perimetre,
            )
        )

    def interroger(
        self, gabarit: str, question: str, codes: list[str] | None = None
    ) -> Interrogation:
        """Ouvre une interrogation et la rend, pour que l'appelant la complète.

        Une par question posée. La rendre plutôt que de la refermer aussitôt est ce qui
        permet d'y attacher **ses** passages, et non ceux de la suivante.
        """
        interrogation = Interrogation(gabarit=gabarit, question=question, codes=codes or [])
        self.trace.interrogations.append(interrogation)
        return interrogation

    def repondue(
        self,
        interrogation: Interrogation,
        issue: str,
        origine: str = "service",
        defauts: list[str] | None = None,
        redaction_indisponible: bool = False,
    ) -> None:
        """Referme une interrogation sur ce que le moteur en a fait."""
        interrogation.issue = issue
        interrogation.origine = origine
        interrogation.defauts = defauts or []
        interrogation.redaction_indisponible = redaction_indisponible

    def passage(
        self,
        interrogation: Interrogation,
        numero: int,
        document: str,
        page: int,
        titre: str = "",
    ) -> None:
        """Attache un passage à l'interrogation qui l'a obtenu."""
        interrogation.passages.append(
            PassageCite(numero=numero, document=document, page=page, titre=titre)
        )

    def refus(self, objet: str, motif: str) -> None:
        """Consigne ce que la passerelle a refusé d'elle-même."""
        self.trace.decisions.append(Decision(objet=objet, motif=motif))

    def degradation(self, cause: str, consequence: str) -> None:
        """Consigne ce qui manquait et ce que son absence a coûté."""
        self.trace.degradations.append(Degradation(cause=cause, consequence=consequence))

    def close(self) -> Trace:
        """Rend la trace assemblée."""
        return self.trace


class Registre:
    """Les dernières traces, en mémoire."""

    def __init__(self, memoire: int = MEMOIRE) -> None:
        self._traces: deque[Trace] = deque(maxlen=memoire)

    def deposer(self, trace: Trace) -> None:
        self._traces.append(trace)

    def dernieres(self, combien: int = 10) -> list[Trace]:
        """Les traces les plus récentes d'abord."""
        return list(reversed(self._traces))[:combien]

    def par_identifiant(self, identifiant: str) -> Trace | None:
        return next((t for t in self._traces if t.identifiant == identifiant), None)

    def vider(self) -> None:
        """Oublie toutes les traces."""
        self._traces.clear()

    def __len__(self) -> int:
        return len(self._traces)

    def __iter__(self) -> Iterator[Trace]:
        return iter(self._traces)


def exporter(trace: Trace) -> str:
    """Rend la trace en JSON, champs dans un ordre stable, pour que deux traces se comparent."""
    return json.dumps(
        trace.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
