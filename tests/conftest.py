"""Les branchements communs aux fichiers de test de l'API.

Deux états de module — le cache des questions et la dernière observation terminologique — sont
vidés avant **et** après chaque test : sans cela, l'ordre des tests déciderait de leur résultat.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from doubles import REPONSE, FausseTerminologie, FauxFhir, faux_documentaliste
from fastapi.testclient import TestClient

from passerelle.api import service
from passerelle.documentaliste.client import Documentaliste
from passerelle.smart.decouverte import DecouverteImpossible


@pytest.fixture
def brancher(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Remplace les deux dépendances extérieures par des doubles."""
    reglages: dict = {
        "fhir": FauxFhir(),
        "statut": 200,
        "charge": REPONSE,
        "terminologie": FausseTerminologie(),
        "joignable": True,
        "appels": [],
    }

    def fhir(*_a: object, **_k: object) -> FauxFhir:
        return reglages["fhir"]

    def documentaliste(*_a: object, **_k: object) -> Documentaliste:
        def repondre(requete: httpx.Request) -> httpx.Response:
            reglages["appels"].append(str(requete.url))
            return httpx.Response(reglages["statut"], json=reglages["charge"])

        return faux_documentaliste(repondre)

    def terminologie(*_a: object, **_k: object) -> FausseTerminologie:
        return reglages["terminologie"]

    def decouvrir(base: str, *_a: object, **_k: object) -> object:
        if not reglages["joignable"]:
            raise DecouverteImpossible(f"{base} : injoignable")
        return object()

    monkeypatch.setattr(service, "ClientFhir", fhir)
    monkeypatch.setattr(service, "Documentaliste", documentaliste)
    # Le service éprouve la terminologie au démarrage : sans ce double, le `TestClient`
    # joindrait le serveur de l'ANS et la suite cesserait d'être hors ligne.
    monkeypatch.setattr(service, "Terminologie", terminologie)
    # Même raison pour les trois serveurs FHIR, éprouvés eux aussi au démarrage.
    monkeypatch.setattr(service, "decouvrir", decouvrir)
    # Deux états de module : sans ce vidage, l'ordre des tests déciderait de leur résultat —
    # celui qui compte les appels au moteur passerait ou non selon ses voisins, et l'état de
    # la terminologie hériterait de l'observation du test précédent.
    service.CACHE.clear()
    service._TERMINOLOGIE.update({"temoin": "", "vue": ""})
    monkeypatch.setenv("RATELIMIT_ENABLED", "false")
    yield reglages
    service.CACHE.clear()
    service._TERMINOLOGIE.update({"temoin": "", "vue": ""})


@pytest.fixture
def client(brancher: dict) -> Iterator[TestClient]:
    from passerelle.api.app import app, registre

    assert brancher, "les dépendances extérieures doivent être remplacées avant le service"
    registre.vider()
    with TestClient(app) as essai:
        yield essai
    registre.vider()
