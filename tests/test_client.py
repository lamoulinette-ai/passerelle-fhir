"""Le transport FHIR, éprouvé sans réseau.

Deux propriétés comptent ici :

- **la pagination** — un `Bundle` de recherche ne rend qu'une page, et un client qui ignore
  le lien `next` rend un dossier tronqué sans jamais échouer ;
- **l'autorisation atteint la requête** — un jeton obtenu, consigné dans la trace, mais
  jamais joint à l'en-tête, ne se voit que devant un serveur qui l'exige.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from passerelle.fhir.client import BASE_DEFAUT, ClientFhir, FhirIndisponible, base, delai

Gestionnaire = Callable[[httpx.Request], httpx.Response]


def _client(gestionnaire: Gestionnaire) -> ClientFhir:
    transport = httpx.MockTransport(gestionnaire)
    return ClientFhir(adresse="https://exemple.test/fhir", client=httpx.Client(transport=transport))


class TestConfiguration:
    def test_la_base_par_defaut_est_le_bac_a_sable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PASSERELLE_FHIR_BASE", raising=False)
        assert base() == BASE_DEFAUT

    def test_une_base_vide_ne_produit_pas_une_url_vide(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Une variable présente mais vide vaut absente, sans quoi le client viserait `/`."""
        monkeypatch.setenv("PASSERELLE_FHIR_BASE", "   ")
        assert base() == BASE_DEFAUT

    def test_un_delai_illisible_degrade_sans_lever(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PASSERELLE_FHIR_DELAI", "bientôt")
        assert delai() == 10.0


class TestAutorisation:
    """Un jeton consigné dans la trace mais absent de la requête est un journal qui ment.

    Les en-têtes se lisent sur le transport que le client construit lui-même : lui injecter
    un transport de test contournerait précisément la fusion qu'on éprouve.
    """

    @staticmethod
    def _entetes(entetes: dict[str, str] | None = None) -> httpx.Headers:
        return ClientFhir(adresse="https://exemple.test/fhir", entetes=entetes)._client.headers

    def test_l_en_tete_d_autorisation_part_avec_la_requete(self) -> None:
        assert self._entetes({"Authorization": "Bearer secret"})["Authorization"] == "Bearer secret"

    def test_accept_survit_a_la_fusion(self) -> None:
        """Un serveur au moins rend 406 sans lui : un appelant ne doit pas pouvoir l'effacer."""
        assert self._entetes({"Accept": "text/plain"})["Accept"] == "application/fhir+json"

    def test_sans_jeton_aucune_autorisation_n_est_envoyee(self) -> None:
        assert "authorization" not in self._entetes()


class TestLecture:
    def test_un_patient_est_rendu(self) -> None:
        def repondre(requete: httpx.Request) -> httpx.Response:
            assert requete.url.path.endswith("/Patient/abc")
            return httpx.Response(200, json={"resourceType": "Patient", "id": "abc"})

        assert _client(repondre).patient("abc")["id"] == "abc"

    def test_une_erreur_http_devient_une_indisponibilite(self) -> None:
        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"resourceType": "OperationOutcome"})

        with pytest.raises(FhirIndisponible):
            _client(repondre).patient("abc")

    def test_une_reponse_qui_n_est_pas_du_fhir_est_refusee(self) -> None:
        """Un portail captif rend un 200 et du HTML : sans ce contrôle, il passerait."""

        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>connectez-vous</html>")

        with pytest.raises(FhirIndisponible):
            _client(repondre).patient("abc")


class TestPagination:
    def test_les_pages_suivantes_sont_suivies(self) -> None:
        pages = {
            "1": {
                "resourceType": "Bundle",
                "entry": [{"resource": {"resourceType": "Condition", "id": "a"}}],
                "link": [{"relation": "next", "url": "https://exemple.test/fhir?page=2"}],
            },
            "2": {
                "resourceType": "Bundle",
                "entry": [{"resource": {"resourceType": "Condition", "id": "b"}}],
                "link": [{"relation": "self", "url": "https://exemple.test/fhir?page=2"}],
            },
        }

        def repondre(requete: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=pages[requete.url.params.get("page", "1")])

        rendues = _client(repondre).conditions("abc")
        assert [ressource["id"] for ressource in rendues] == ["a", "b"]

    def test_un_bundle_vide_rend_une_liste_vide(self) -> None:
        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"resourceType": "Bundle"})

        assert _client(repondre).conditions("abc") == []
