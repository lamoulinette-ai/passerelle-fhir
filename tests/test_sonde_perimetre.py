"""Ce que la sonde du périmètre mesure, et ce qu'elle refuse de conclure.

Trois propriétés priment :

- **une rédaction indisponible n'est pas un échec** — les passages sont ce qui fonde le
  périmètre, la synthèse ne l'est pas ; confondre les deux rendrait la mesure impossible
  chaque fois que le fournisseur du modèle est coupé ;
- **un service injoignable ne vaut pas un corpus muet** — sans cette distinction, une panne
  de réseau ferait sortir deux codes du périmètre ;
- **aucun repli sur les réponses enregistrées** — elles ont été retrouvées pour d'autres
  questions, et fonderaient le périmètre sur une coïncidence.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from passerelle.documentaliste.client import Documentaliste
from passerelle.requete.perimetre import ECARTES
from passerelle.sondes.perimetre import QUESTIONS, en_markdown, interroger

Gestionnaire = Callable[[httpx.Request], httpx.Response]
BASE = "https://exemple.test"

#: Les deux codes de la BPCO que la sonde a éprouvés, et que l'interrogation a fait sortir.
EPROUVES = {"185086009", "87433001"}


def _moteur(gestionnaire: Gestionnaire) -> Documentaliste:
    transport = httpx.MockTransport(gestionnaire)
    return Documentaliste(adresse=BASE, client=httpx.Client(transport=transport))


def _passage(numero: int = 1, texte: str = "La BPCO regroupe plusieurs formes.") -> dict:
    return {
        "numero": numero,
        "document": "app_323_guide_bpco_actu_2019_vf",
        "page": 12,
        "texte": texte,
        "titre": "Guide du parcours de soins BPCO",
        "url": "https://www.has-sante.fr/jcms/c_1242507/",
    }


def _repond(charge: dict, journal: list[httpx.Request] | None = None) -> Gestionnaire:
    def repondre(requete: httpx.Request) -> httpx.Response:
        if journal is not None:
            journal.append(requete)
        return httpx.Response(200, json=charge)

    return repondre


def _reponse(**surcharges: object) -> dict:
    charge: dict = {
        "question": "q",
        "issue": "reponse",
        "affirmations": [],
        "passages": [_passage()],
        "defauts": [],
        "redaction_indisponible": False,
    }
    charge.update(surcharges)
    return charge


def _observations(gestionnaire: Gestionnaire) -> list:
    moteur = _moteur(gestionnaire)
    try:
        return interroger(moteur=moteur, espacement=0)
    finally:
        moteur.fermer()


class TestQuestionsDeclarees:
    def test_chaque_code_eprouve_a_sa_question(self) -> None:
        """La sonde éprouve exactement les codes qu'aucune source ne justifiait."""
        vises = {question.code for question in QUESTIONS if question.code}
        assert vises == EPROUVES

    def test_les_codes_eprouves_ont_ete_ecartes(self) -> None:
        """La sonde est l'instrument qui a produit l'exclusion ; les deux doivent concorder.

        Si un de ces codes revenait au périmètre sans que la sonde soit rejouée, ce test le
        dirait. C'est ce qui empêche de défaire l'arbitrage en silence.
        """
        assert EPROUVES <= set(ECARTES)

    def test_chaque_question_declare_son_attendu(self) -> None:
        """Le critère est posé avant la mesure, sans quoi on choisit la preuve après coup."""
        assert all(question.attendu.strip() for question in QUESTIONS)

    def test_une_question_n_impose_aucune_reponse(self) -> None:
        """« la bronchite chronique obstructive **est** une BPCO » orienterait la recherche.

        Une question fermée laisse au corpus la possibilité de ne rien rendre ; une
        affirmation déguisée en requête ramène les passages qui la confirment.
        """
        marqueurs = ("quelles", "quel", "-elle", "-il")
        for question in QUESTIONS:
            assert question.intitule.endswith("?")
            assert any(marqueur in question.intitule for marqueur in marqueurs)


class TestMesure:
    def test_chaque_question_est_posee_une_fois(self) -> None:
        vues: list[httpx.Request] = []
        _observations(_repond(_reponse(), vues))
        assert len(vues) == len(QUESTIONS)
        assert all(requete.url.path == "/question" for requete in vues)

    def test_la_question_posee_est_celle_qui_est_declaree(self) -> None:
        vues: list[httpx.Request] = []
        _observations(_repond(_reponse(), vues))
        corps = [requete.content.decode("utf-8") for requete in vues]
        for question, envoye in zip(QUESTIONS, corps, strict=True):
            assert question.intitule in json.loads(envoye)["question"]

    def test_les_passages_sont_conserves(self) -> None:
        observations = _observations(_repond(_reponse()))
        assert all(observation.passages for observation in observations)
        assert observations[0].passages[0].page == 12


class TestRedactionIndisponible:
    def test_une_synthese_manquante_reste_une_mesure(self) -> None:
        """Mistral coupé, la recherche a eu lieu : c'est elle qui fonde le périmètre."""
        charge = _reponse(redaction_indisponible=True, affirmations=[])
        observations = _observations(_repond(charge))
        for observation in observations:
            assert observation.mesuree
            assert observation.redaction_indisponible
            assert observation.passages

    def test_aucun_repli_sur_les_reponses_enregistrees(self) -> None:
        """Un repli servirait des passages retrouvés pour une autre question."""
        charge = _reponse(redaction_indisponible=True)
        observations = _observations(_repond(charge))
        documents = {p.document for o in observations for p in o.passages}
        assert documents == {"app_323_guide_bpco_actu_2019_vf"}


class TestDegradation:
    def test_un_service_injoignable_se_dit_indetermine(self) -> None:
        def tomber(_requete: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("injoignable")

        observations = _observations(tomber)
        assert all(observation.issue == "indéterminé" for observation in observations)
        assert all(not observation.mesuree for observation in observations)
        assert all(observation.cause for observation in observations)

    def test_un_constat_d_absence_est_une_mesure(self) -> None:
        """Le corpus qui ne dit rien répond quelque chose ; le réseau coupé, non."""
        charge = _reponse(issue="constat_absence", passages=[])
        observations = _observations(_repond(charge))
        assert all(observation.mesuree for observation in observations)


class TestRendu:
    def test_le_rendu_porte_la_page_et_la_fiche(self) -> None:
        """Un extrait sans référence n'est pas une source, c'est une allégation."""
        rendu = en_markdown(_observations(_repond(_reponse())))
        assert "page 12" in rendu
        assert "https://www.has-sante.fr/jcms/c_1242507/" in rendu

    def test_le_rendu_rappelle_qu_il_ne_conclut_pas(self) -> None:
        rendu = en_markdown(_observations(_repond(_reponse())))
        assert "ne conclut pas" in rendu

    def test_l_attendu_figure_en_regard_des_passages(self) -> None:
        rendu = en_markdown(_observations(_repond(_reponse())))
        assert all(question.attendu in rendu for question in QUESTIONS)

    def test_l_extrait_est_borne_et_signale_sa_coupe(self) -> None:
        charge = _reponse(passages=[_passage(texte="x" * 900)])
        rendu = en_markdown(_observations(_repond(charge)), caracteres=100)
        assert "[…]" in rendu
        assert "x" * 200 not in rendu

    def test_zero_rend_le_texte_entier(self) -> None:
        charge = _reponse(passages=[_passage(texte="y" * 900)])
        rendu = en_markdown(_observations(_repond(charge)), caracteres=0)
        assert "y" * 900 in rendu

    def test_une_absence_de_passage_est_dite(self) -> None:
        charge = _reponse(issue="constat_absence", passages=[])
        rendu = en_markdown(_observations(_repond(charge)))
        assert "Aucun passage retrouvé" in rendu
