"""Ce qui distingue une traduction d'un repli.

La propriété centrale : **le serveur rend un `display` dans tous les cas**, y compris pour un
concept jamais traduit en français. Se fier à lui donnerait un taux de correspondance de cent
pour cent, dont une part serait de l'anglais déguisé.

Seule l'existence d'une désignation de langue `fr` fait foi.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from passerelle.terminologie.client import (
    ConceptInconnu,
    Terminologie,
    TerminologieIndisponible,
)

Gestionnaire = Callable[[httpx.Request], httpx.Response]
BASE = "https://exemple.test/fhir"


def _client(gestionnaire: Gestionnaire) -> Terminologie:
    transport = httpx.MockTransport(gestionnaire)
    return Terminologie(adresse=BASE, client=httpx.Client(transport=transport))


def _parametres(*parametres: dict) -> dict:
    return {"resourceType": "Parameters", "parameter": list(parametres)}


def _designation(langue: str, valeur: str) -> dict:
    return {
        "name": "designation",
        "part": [
            {"name": "language", "valueCode": langue},
            {"name": "value", "valueString": valeur},
        ],
    }


def _designation_usage(langue: str, valeur: str, usage: str) -> dict:
    """Une désignation portant son usage, comme le serveur en rend."""
    return {
        "name": "designation",
        "part": [
            {"name": "language", "valueCode": langue},
            {"name": "use", "valueCoding": {"code": usage}},
            {"name": "value", "valueString": valeur},
        ],
    }


def _repond(charge: dict, statut: int = 200) -> Gestionnaire:
    def repondre(_requete: httpx.Request) -> httpx.Response:
        return httpx.Response(statut, json=charge)

    return repondre


class TestResolution:
    def test_une_designation_francaise_est_retenue(self) -> None:
        charge = _parametres(
            {"name": "display", "valueString": "diabète de type 2"},
            _designation("en", "Diabetes mellitus type 2"),
            _designation("fr", "diabète de type 2"),
        )
        concept = _client(_repond(charge)).resoudre("http://snomed.info/sct", "44054006")
        assert concept.resolu
        assert concept.libelle_fr == "diabète de type 2"

    def test_le_terme_prefere_l_emporte_sur_un_synonyme_place_avant(self) -> None:
        """Le cas réel de `271737000` : « anemia » précède « anémie » dans la réponse.

        Prendre la première désignation française rendait un synonyme anglophone estampillé
        français, et la question posée au corpus partait dans la mauvaise langue.
        """
        charge = _parametres(
            {"name": "display", "valueString": "anémie"},
            _designation_usage("fr", "anemia", "Synonym"),
            _designation_usage("fr", "anémie", "preferredForLanguage"),
        )
        assert _client(_repond(charge)).resoudre("s", "271737000").libelle_fr == "anémie"

    def test_l_usage_est_lu_sur_son_code_et_non_sur_son_affichage(self) -> None:
        """Le serveur écrit `preferredForLanguage` ici et `Preferred For Language` là."""
        charge = _parametres(
            _designation_usage("fr", "synonyme", "Synonym"),
            _designation_usage("fr-x-sctlang-10031000-315102", "préféré", "Preferred For Language"),
        )
        assert _client(_repond(charge)).resoudre("s", "c").libelle_fr == "préféré"

    def test_sans_usage_declare_la_premiere_francaise_sert_de_repli(self) -> None:
        """Un serveur qui n'annote pas ses désignations ne doit pas faire perdre le libellé."""
        charge = _parametres(_designation("fr", "libellé sans usage"))
        assert _client(_repond(charge)).resoudre("s", "c").libelle_fr == "libellé sans usage"

    def test_un_terme_prefere_dans_une_autre_langue_ne_compte_pas(self) -> None:
        """Sinon l'anglais préféré l'emporterait sur le français synonyme."""
        charge = _parametres(
            _designation_usage("en", "Anemia", "preferredForLanguage"),
            _designation_usage("fr", "anémie", "Synonym"),
        )
        assert _client(_repond(charge)).resoudre("s", "c").libelle_fr == "anémie"

    def test_une_variante_regionale_compte(self) -> None:
        """Le module français emploie `fr-x-sctlang-…`, pas `fr` seul."""
        charge = _parametres(
            _designation("fr-x-sctlang-10031000-315102", "diabète de type 2"),
        )
        assert _client(_repond(charge)).resoudre("s", "c").resolu

    def test_sans_designation_francaise_le_concept_n_est_pas_resolu(self) -> None:
        """Le cas qui fausserait le taux : un `display` revient quand même.

        Le compter comme résolu publierait un taux de correspondance flatteur et faux.
        """
        charge = _parametres(
            {"name": "display", "valueString": "Pulmonary emphysema"},
            _designation("en", "Pulmonary emphysema"),
        )
        concept = _client(_repond(charge)).resoudre("s", "87433001")
        assert not concept.resolu
        assert concept.libelle_fr is None
        assert concept.display == "Pulmonary emphysema"

    def test_le_libelle_retombe_sur_le_display(self) -> None:
        """Faute de français, on affiche ce qu'on a — mais on ne le compte pas comme résolu."""
        charge = _parametres({"name": "display", "valueString": "Pulmonary emphysema"})
        assert _client(_repond(charge)).resoudre("s", "c").libelle == "Pulmonary emphysema"

    def test_la_version_est_conservee(self) -> None:
        """Un libellé sans version n'est pas reproductible."""
        charge = _parametres(
            {"name": "version", "valueString": "http://snomed.info/sct/11000315107/version/2026"},
            _designation("fr", "diabète"),
        )
        assert "11000315107" in _client(_repond(charge)).resoudre("s", "c").version


class TestCache:
    def test_un_concept_deja_vu_n_est_pas_redemande(self) -> None:
        appels: list[int] = []

        def repondre(_requete: httpx.Request) -> httpx.Response:
            appels.append(1)
            return httpx.Response(200, json=_parametres(_designation("fr", "x")))

        terminologie = _client(repondre)
        terminologie.resoudre("s", "c")
        terminologie.resoudre("s", "c")
        assert len(appels) == 1

    def test_deux_codes_distincts_sont_demandes(self) -> None:
        appels: list[int] = []

        def repondre(_requete: httpx.Request) -> httpx.Response:
            appels.append(1)
            return httpx.Response(200, json=_parametres(_designation("fr", "x")))

        terminologie = _client(repondre)
        terminologie.resoudre("s", "c1")
        terminologie.resoudre("s", "c2")
        assert len(appels) == 2


class TestDegradation:
    def test_une_panne_leve_une_indisponibilite(self) -> None:
        def tomber(_requete: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("injoignable")

        with pytest.raises(TerminologieIndisponible):
            _client(tomber).resoudre("s", "c")

    def test_une_reponse_qui_n_est_pas_des_parametres_est_refusee(self) -> None:
        """Un portail captif rend un 200 et du HTML."""
        with pytest.raises(TerminologieIndisponible):
            _client(_repond({"resourceType": "OperationOutcome"})).resoudre("s", "c")

    def test_une_erreur_http_est_refusee(self) -> None:
        with pytest.raises(TerminologieIndisponible):
            _client(_repond({}, 503)).resoudre("s", "c")


class TestConceptInconnu:
    """Un référentiel que le serveur français n'héberge pas n'est pas une panne du serveur."""

    def test_un_404_nomme_le_concept_inconnu(self) -> None:
        with pytest.raises(ConceptInconnu):
            _client(_repond({}, 404)).resoudre("http://hl7.org/fhir/sid/icd-10-cm", "I11.0")

    def test_il_reste_une_indisponibilite_pour_qui_ne_fait_pas_la_difference(self) -> None:
        """Les sondes attrapent `TerminologieIndisponible` : la sous-classe les laisse intactes."""
        assert issubclass(ConceptInconnu, TerminologieIndisponible)

    def test_une_panne_n_est_pas_un_concept_inconnu(self) -> None:
        """La distinction doit tenir dans les deux sens, sans quoi elle n'en est pas une."""
        with pytest.raises(TerminologieIndisponible) as leve:
            _client(_repond({}, 503)).resoudre("s", "c")
        assert not isinstance(leve.value, ConceptInconnu)


class TestRequete:
    def test_la_langue_est_demandee_explicitement(self) -> None:
        """Le serveur français répond déjà en français ; un paramètre déclaré vaut mieux
        qu'un comportement supposé."""
        vues: list[httpx.Request] = []

        def repondre(requete: httpx.Request) -> httpx.Response:
            vues.append(requete)
            return httpx.Response(200, json=_parametres())

        _client(repondre).resoudre("http://snomed.info/sct", "44054006")
        assert vues[0].url.params["displayLanguage"] == "fr"
        assert vues[0].url.params["code"] == "44054006"
