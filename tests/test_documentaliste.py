"""Ce que le client fait quand le service répond, et quand il ne répond pas.

Deux propriétés valent tous les autres tests de ce fichier :

- **le client ne lève jamais** — panne, délai, erreur du service : il sert la réponse
  enregistrée du gabarit. Une exception remonterait jusqu'à la page et transformerait une
  indisponibilité passagère en écran blanc ;
- **la cause du repli est toujours rendue**, même quand le repli réussit. Une réponse
  enregistrée servie sans cause serait indiscernable d'une réponse vive, et le journal
  affirmerait une interrogation qui n'a pas eu lieu.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from passerelle.documentaliste.client import Documentaliste, enregistree

EXEMPLES = Path(__file__).parent / "exemples" / "reponses"
Gestionnaire = Callable[[httpx.Request], httpx.Response]

VIVE = {
    "question": "quelle est la prise en charge recommandée du diabète de type 2 ?",
    "issue": "reponse",
    "affirmations": [{"texte": "Une phrase citée.", "extrait": 1}],
    "passages": [
        {"numero": 1, "document": "has_1234", "page": 12, "texte": "Un passage.", "titre": "Guide"}
    ],
    "defauts": [],
    "redaction_indisponible": False,
}


def _moteur(gestionnaire: Gestionnaire) -> Documentaliste:
    return Documentaliste(
        adresse="https://exemple.test",
        client=httpx.Client(transport=httpx.MockTransport(gestionnaire)),
        exemples=EXEMPLES,
    )


def _repond(charge: dict, statut: int = 200) -> Gestionnaire:
    def repondre(_requete: httpx.Request) -> httpx.Response:
        return httpx.Response(statut, json=charge)

    return repondre


class TestAppel:
    def test_une_reponse_du_service_est_rendue_telle_quelle(self) -> None:
        reponse, cause = _moteur(_repond(VIVE)).interroger("une question", "diabete")
        assert cause == ""
        assert reponse is not None
        assert reponse.issue == "reponse"
        assert reponse.passages[0].document == "has_1234"
        assert not reponse.enregistree

    def test_la_question_part_en_json(self) -> None:
        vues: list[bytes] = []

        def repondre(requete: httpx.Request) -> httpx.Response:
            vues.append(requete.content)
            return httpx.Response(200, json=VIVE)

        _moteur(repondre).interroger("ma question", "diabete")
        assert json.loads(vues[0]) == {"question": "ma question"}

    def test_un_refus_n_est_pas_une_panne(self) -> None:
        """Un refus est une décision du moteur : il se rend, il ne déclenche pas de repli."""
        refus = {**VIVE, "issue": "refus", "refus": "aucun passage ne porte sur la question"}
        reponse, cause = _moteur(_repond(refus)).interroger("une question", "diabete")
        assert cause == ""
        assert reponse is not None and reponse.issue == "refus"

    def test_une_redaction_coupee_sert_la_reponse_enregistree(self) -> None:
        """Le fournisseur du modèle a déjà coupé son palier gratuit vingt-cinq heures durant.

        La rédaction vive ne peut donc pas être le chemin nominal d'une démonstration
        publique : une réponse enregistrée, déclarée comme telle, vaut mieux qu'un refus
        qui n'en est pas un.
        """
        coupee = {**VIVE, "redaction_indisponible": True, "affirmations": []}
        reponse, cause = _moteur(_repond(coupee)).interroger("une question", "diabete")
        assert reponse is not None and reponse.enregistree
        assert "rédaction indisponible" in cause

    def test_sans_enregistrement_la_reponse_amputee_est_rendue(self) -> None:
        """Les passages retrouvés valent mieux que rien, et la cause dit ce qui manque."""
        coupee = {**VIVE, "redaction_indisponible": True, "affirmations": []}
        reponse, cause = _moteur(_repond(coupee)).interroger("une question", "bpco")
        assert reponse is not None and not reponse.enregistree
        assert reponse.redaction_indisponible and reponse.passages
        assert "aucune réponse enregistrée" in cause

    def test_une_reponse_redigee_ne_declenche_rien(self) -> None:
        reponse, cause = _moteur(_repond(VIVE)).interroger("une question", "diabete")
        assert cause == ""
        assert reponse is not None and not reponse.redaction_indisponible


class TestRepli:
    def test_une_erreur_du_service_declenche_le_repli(self) -> None:
        reponse, cause = _moteur(_repond({}, 503)).interroger("une question", "diabete")
        assert reponse is not None and reponse.enregistree
        assert "503" in cause

    def test_une_panne_reseau_declenche_le_repli(self) -> None:
        def tomber(_requete: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("injoignable")

        reponse, cause = _moteur(tomber).interroger("une question", "diabete")
        assert reponse is not None and reponse.enregistree
        assert "injoignable" in cause

    def test_une_reponse_illisible_declenche_le_repli(self) -> None:
        def repondre(_requete: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>portail</html>")

        reponse, cause = _moteur(repondre).interroger("une question", "diabete")
        assert reponse is not None and reponse.enregistree
        assert cause

    def test_sans_gabarit_aucun_repli_n_est_tente(self) -> None:
        """Ne pas demander de repli et n'en pas trouver sont deux choses différentes.

        La cause rendue est celle de l'échec, sans mention d'une réponse enregistrée qui
        n'a jamais été cherchée.
        """
        reponse, cause = _moteur(_repond({}, 503)).interroger("une question", "")
        assert reponse is None
        assert cause == "service en erreur (503)"
        assert "enregistrée" not in cause

    def test_un_gabarit_sans_exemple_echoue_en_le_disant(self) -> None:
        """Ici le repli est demandé, et c'est le fichier qui manque : la cause le dit."""
        reponse, cause = _moteur(_repond({}, 503)).interroger("une question", "bpco")
        assert reponse is None
        assert "aucune réponse enregistrée" in cause
        assert "bpco" in cause


class TestEnregistrees:
    def test_une_reponse_enregistree_se_lit(self) -> None:
        reponse = enregistree("diabete", EXEMPLES)
        assert reponse is not None and reponse.passages

    def test_elle_se_declare_enregistree(self) -> None:
        """Indiscernable d'une réponse vive pour l'appelant, distinguable dans la trace."""
        reponse = enregistree("diabete", EXEMPLES)
        assert reponse is not None
        assert reponse.enregistree and reponse.origine == "enregistrée"

    def test_un_gabarit_inconnu_rend_none(self) -> None:
        assert enregistree("inexistant", EXEMPLES) is None

    def test_un_fichier_abime_rend_none_sans_lever(self, tmp_path: Path) -> None:
        (tmp_path / "diabete.json").write_text("{ pas du json", encoding="utf-8")
        assert enregistree("diabete", tmp_path) is None
