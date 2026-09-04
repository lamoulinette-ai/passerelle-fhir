"""Ce que les gabarits construisent, et ce qu'ils refusent de construire.

Trois propriétés valent tous les autres tests de ce fichier :

- **un contexte hors périmètre ne produit aucune requête**, jamais une requête creuse —
  n'avoir rien à demander n'est pas demander quelque chose de vide ;
- **aucune formulation produite n'est impérative** — c'est la règle 2 de la conception, et
  c'est ce qui sépare un outil documentaire d'une aide à la décision ;
- **le code générique et son descendant mènent au même gabarit** — les données observées
  n'emploient que des descendants, un autre serveur emploiera le générique.
"""

from __future__ import annotations

from passerelle.fhir.schemas import SYSTEME_SNOMED, CodeClinique, ContextePatient, Probleme
from passerelle.requete.gabarits import FORMULATIONS, Forme, apparier, construire
from passerelle.requete.perimetre import ECARTES, PATHOLOGIES, pathologie

IMPERATIFS = (
    "prescrivez",
    "orientez",
    "surveillez",
    "administrez",
    "il faut",
    "vous devez",
    "doit être",
)


def _contexte(*codes: tuple[str, str]) -> ContextePatient:
    """Un contexte porteur des codes donnés, avec leur statut clinique."""
    return ContextePatient(
        identifiant="essai",
        problemes=[
            Probleme(code=CodeClinique(systeme=SYSTEME_SNOMED, code=code), statut=statut)
            for code, statut in codes
        ],
    )


class TestPerimetre:
    def test_un_code_du_perimetre_est_reconnu(self) -> None:
        assert pathologie(SYSTEME_SNOMED, "44054006").identifiant == "diabete"

    def test_un_code_hors_perimetre_ne_l_est_pas(self) -> None:
        assert pathologie(SYSTEME_SNOMED, "444814009") is None

    def test_un_autre_systeme_n_apparie_pas(self) -> None:
        """Un code LOINC identique en chiffres ne désigne pas la même chose."""
        assert pathologie("http://loinc.org", "44054006") is None

    def test_le_prediabete_est_ecarte_et_documente(self) -> None:
        """Son exclusion est un choix, pas un oubli : elle est consignée avec sa raison."""
        assert pathologie(SYSTEME_SNOMED, "15777000") is None
        assert "15777000" in ECARTES and ECARTES["15777000"]

    def test_chaque_pathologie_porte_son_article(self) -> None:
        assert all(patho.article for patho in PATHOLOGIES)


class TestAppariement:
    def test_seules_les_conditions_actives_sont_appariees(self) -> None:
        contexte = _contexte(("44054006", "active"), ("88805009", "resolved"))
        apparies = apparier(contexte)
        assert set(apparies) == {"diabete"}

    def test_un_generique_et_son_descendant_menent_au_meme_gabarit(self) -> None:
        descendant = apparier(_contexte(("185086009", "active")))
        generique = apparier(_contexte(("13645005", "active")))
        assert set(descendant) == set(generique) == {"bpco"}

    def test_deux_codes_d_une_meme_pathologie_ne_font_qu_un_gabarit(self) -> None:
        apparies = apparier(_contexte(("44054006", "active"), ("368581000119106", "active")))
        assert set(apparies) == {"diabete"}
        assert len(apparies["diabete"]) == 2


class TestConstruction:
    def test_un_contexte_hors_perimetre_ne_produit_rien(self) -> None:
        assert construire(_contexte(("444814009", "active"))) == []

    def test_un_contexte_vide_ne_produit_rien(self) -> None:
        assert construire(ContextePatient(identifiant="essai")) == []

    def test_deux_pathologies_produisent_deux_requetes(self) -> None:
        """Jamais fusionnées : une question fusionnée n'a aucun document qui y réponde."""
        requetes = construire(_contexte(("44054006", "active"), ("185086009", "active")))
        assert len(requetes) == 2
        assert {r.gabarit for r in requetes} == {"diabete", "bpco"}

    def test_l_ordre_suit_le_perimetre_et_non_le_dossier(self) -> None:
        """L'ordre des ressources d'un serveur FHIR n'est pas garanti."""
        premier = construire(_contexte(("185086009", "active"), ("44054006", "active")))
        second = construire(_contexte(("44054006", "active"), ("185086009", "active")))
        assert [r.gabarit for r in premier] == [r.gabarit for r in second]

    def test_les_codes_ayant_declenche_sont_consignes(self) -> None:
        requete = construire(_contexte(("44054006", "active")))[0]
        assert requete.codes == ["44054006"]


class TestFormulation:
    def test_la_forme_phrasee_est_interrogative(self) -> None:
        requete = construire(_contexte(("44054006", "active")), Forme.PRISE_EN_CHARGE)[0]
        assert requete.texte.endswith("?")
        assert "diabète de type 2" in requete.texte

    def test_la_forme_nue_est_le_libelle_seul(self) -> None:
        requete = construire(_contexte(("44054006", "active")), Forme.LIBELLE)[0]
        assert requete.texte == "diabète de type 2"

    def test_les_deux_formes_partagent_gabarit_et_codes(self) -> None:
        """Sans quoi la mesure du jour 9 comparerait deux implémentations."""
        contexte = _contexte(("44054006", "active"))
        nue = construire(contexte, Forme.LIBELLE)[0]
        phrasee = construire(contexte, Forme.PRISE_EN_CHARGE)[0]
        assert nue.gabarit == phrasee.gabarit
        assert nue.codes == phrasee.codes
        assert nue.texte != phrasee.texte

    def test_aucune_formulation_n_est_imperative(self) -> None:
        """Sur **toutes** les formulations candidates, y compris celles ajoutées plus tard."""
        contexte = _contexte(
            ("44054006", "active"), ("88805009", "active"), ("185086009", "active")
        )
        for forme in Forme:
            for requete in construire(contexte, forme):
                minuscule = requete.texte.lower()
                assert not any(mot in minuscule for mot in IMPERATIFS)

    def test_chaque_forme_a_son_gabarit(self) -> None:
        """Une forme déclarée sans gabarit lèverait au moment de construire, pas ici."""
        assert set(FORMULATIONS) == set(Forme)

    def test_les_articles_sont_corrects(self) -> None:
        """« du bronchopneumopathie » est ce qu'une heuristique aurait produit."""
        contexte = _contexte(
            ("44054006", "active"), ("88805009", "active"), ("185086009", "active")
        )
        textes = {r.gabarit: r.texte for r in construire(contexte, Forme.PRISE_EN_CHARGE)}
        assert "du diabète" in textes["diabete"]
        assert "de l'insuffisance" in textes["insuffisance_cardiaque"]
        assert "de la bronchopneumopathie" in textes["bpco"]

    def test_chaque_formulation_est_rendue_mot_pour_mot(self) -> None:
        """Le rendu réel de chaque gabarit, figé.

        Deux fautes de français ont déjà été écrites ici — « du  diabète » et « sur
        insuffisance cardiaque ». Aucune n'aurait échoué à un test de forme générale ; il
        faut lire les phrases.
        """
        contexte = _contexte(("185086009", "active"))
        attendus = {
            Forme.LIBELLE: "bronchopneumopathie chronique obstructive",
            Forme.PRISE_EN_CHARGE: (
                "quelle est la prise en charge recommandée de la bronchopneumopathie "
                "chronique obstructive ?"
            ),
            Forme.PARCOURS: (
                "quel parcours de soins la Haute Autorité de Santé décrit-elle pour la "
                "bronchopneumopathie chronique obstructive ?"
            ),
            Forme.SUIVI: (
                "quel suivi la Haute Autorité de Santé décrit-elle pour la "
                "bronchopneumopathie chronique obstructive ?"
            ),
            Forme.PUBLICATIONS: (
                "que publie la Haute Autorité de Santé sur la bronchopneumopathie "
                "chronique obstructive ?"
            ),
        }
        for forme, attendu in attendus.items():
            assert construire(contexte, forme)[0].texte == attendu

    def test_aucune_formulation_ne_porte_d_espace_double(self) -> None:
        contexte = _contexte(
            ("44054006", "active"), ("88805009", "active"), ("185086009", "active")
        )
        for forme in Forme:
            for requete in construire(contexte, forme):
                assert "  " not in requete.texte
