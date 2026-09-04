"""Ce que la sonde observe, et ce qu'elle ne fait jamais.

La propriété qui prime : **la sonde n'émet aucune requête modifiante.** Elle interroge des
bacs à sable partagés entre développeurs ; une écriture accidentelle y abîmerait le travail
d'autrui, et rien dans une sortie de sonde ne la signalerait.

La seconde : une observation impossible se dit `indéterminé` et ne se déduit pas. Un serveur
injoignable ne prouve ni qu'il applique les scopes ni qu'il ne les applique pas.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from passerelle.sondes.conformite import en_markdown, observer

EXEMPLES = Path(__file__).parent / "exemples"
Gestionnaire = Callable[[httpx.Request], httpx.Response]
BASE = "https://exemple.test/fhir"

CONFIGURATION = json.loads((EXEMPLES / "smart_configuration.json").read_text(encoding="utf-8"))


def _client(gestionnaire: Gestionnaire) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(gestionnaire))


def _serveur(
    ouvert: bool = True,
    rejette_jeton_invalide: bool = True,
    applique_scope: bool = False,
    journal: list[httpx.Request] | None = None,
) -> Gestionnaire:
    """Un serveur d'essai dont on choisit les propriétés."""

    def repondre(requete: httpx.Request) -> httpx.Response:
        if journal is not None:
            journal.append(requete)
        autorisation = requete.headers.get("Authorization", "")
        if requete.url.path.endswith("/.well-known/smart-configuration"):
            return httpx.Response(200, json=CONFIGURATION)
        if autorisation == "Bearer jeton-invalide":
            return httpx.Response(401 if rejette_jeton_invalide else 200, json={})
        if "/Patient/" in requete.url.path and autorisation:
            return httpx.Response(403 if applique_scope else 200, json={})
        return httpx.Response(200 if ouvert else 401, json={"resourceType": "Bundle", "total": 1})

    return repondre


class TestInnocuite:
    def test_aucune_requete_modifiante(self) -> None:
        vues: list[httpx.Request] = []
        observer(BASE, "jeton", "autre-patient", _client(_serveur(journal=vues)))
        assert vues, "la sonde n'a rien émis, le test ne prouverait rien"
        assert all(requete.method == "GET" for requete in vues)

    def test_le_sondage_ne_rapatrie_pas_de_donnees(self) -> None:
        """`_summary=count` rend un décompte, pas des dossiers."""
        vues: list[httpx.Request] = []
        observer(BASE, client=_client(_serveur(journal=vues)))
        sondages = [r for r in vues if r.url.path.endswith("/Patient")]
        assert all(r.url.params.get("_summary") == "count" for r in sondages)

    def test_le_nombre_de_requetes_reste_petit(self) -> None:
        vues: list[httpx.Request] = []
        observer(BASE, "jeton", "autre-patient", _client(_serveur(journal=vues)))
        assert len(vues) <= 5


class TestObservations:
    def test_la_decouverte_est_interpretee(self) -> None:
        constat = observer(BASE, client=_client(_serveur()))
        assert constat.decouverte
        assert constat.pkce_s256
        assert constat.lancement_autonome
        assert constat.scopes_v1 and constat.scopes_v2

    def test_la_lecture_anonyme_est_constatee(self) -> None:
        assert observer(BASE, client=_client(_serveur(ouvert=True))).lecture_anonyme == "oui"

    def test_une_lecture_anonyme_refusee_est_constatee(self) -> None:
        constat = observer(BASE, client=_client(_serveur(ouvert=False)))
        assert constat.lecture_anonyme.startswith("non")

    def test_le_rejet_d_un_jeton_invalide_est_constate(self) -> None:
        constat = observer(BASE, client=_client(_serveur(rejette_jeton_invalide=True)))
        assert constat.jeton_invalide_rejete == "oui"

    def test_un_serveur_qui_accepte_tout_est_constate(self) -> None:
        constat = observer(BASE, client=_client(_serveur(rejette_jeton_invalide=False)))
        assert constat.jeton_invalide_rejete.startswith("non")


class TestScope:
    def test_un_scope_non_applique_est_nomme(self) -> None:
        constat = observer(BASE, "jeton", "autre", _client(_serveur(applique_scope=False)))
        assert constat.scope_applique.startswith("non")

    def test_un_scope_applique_est_nomme(self) -> None:
        constat = observer(BASE, "jeton", "autre", _client(_serveur(applique_scope=True)))
        assert constat.scope_applique.startswith("oui")

    def test_sans_jeton_le_constat_reste_indetermine(self) -> None:
        """Ne pas avoir éprouvé n'est pas avoir constaté une absence."""
        constat = observer(BASE, client=_client(_serveur()))
        assert constat.scope_applique == "indéterminé"
        assert any("scope non éprouvée" in remarque for remarque in constat.remarques)


class TestDegradation:
    def test_une_base_injoignable_ne_leve_pas(self) -> None:
        def tomber(_requete: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("injoignable")

        constat = observer(BASE, client=_client(tomber))
        assert not constat.decouverte
        assert constat.lecture_anonyme == "indéterminé"
        assert constat.remarques

    def test_une_absence_de_configuration_n_empeche_pas_le_reste(self) -> None:
        """Un serveur sans SMART reste observable sur ses autres propriétés."""

        def repondre(requete: httpx.Request) -> httpx.Response:
            if ".well-known" in requete.url.path:
                return httpx.Response(404, text="")
            return httpx.Response(200, json={"resourceType": "Bundle"})

        constat = observer(BASE, client=_client(repondre))
        assert not constat.decouverte
        assert constat.lecture_anonyme == "oui"


class TestRendu:
    def test_le_tableau_est_collable(self) -> None:
        rendu = en_markdown(observer(BASE, client=_client(_serveur())))
        assert rendu.count("|") > 10
        assert "| observation | constat |" in rendu
        assert BASE in rendu
