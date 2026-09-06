"""Ce que les gabarits formulent, et ce qu'ils refusent de formuler.

Trois propriétés valent tous les autres tests de ce fichier :

- **aucune formulation produite n'est impérative** — c'est la règle 2 de la conception, et
  c'est ce qui sépare un outil documentaire d'une aide à la décision ;
- **le code générique et son descendant mènent à la même pathologie** — les données
  observées n'emploient que des descendants, un autre serveur emploiera le générique ;
- **la forme libre n'accorde aucun article** — elle reçoit un libellé quelconque, dont
  aucune heuristique ne déduit le genre.
"""

from __future__ import annotations

from passerelle.fhir.schemas import SYSTEME_SNOMED, CodeClinique, ContextePatient, Probleme
from passerelle.requete.gabarits import FORMULATIONS, Forme, apparier, question_libre, texte
from passerelle.requete.perimetre import ECARTES, PATHOLOGIES, Pathologie, pathologie

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

    def test_chaque_ecarte_porte_son_motif(self) -> None:
        """Une exclusion est un choix, pas un oubli : elle est consignée avec sa raison."""
        for code, motif in ECARTES.items():
            assert pathologie(SYSTEME_SNOMED, code) is None
            assert motif.strip()

    def test_les_deux_codes_bpco_sont_sortis_apres_interrogation_du_corpus(self) -> None:
        """Ils avaient été retenus sur la foi de leur libellé anglais, sans autre source.

        Le corpus de la HAS a été interrogé sur chacun : aucun passage ne les rattache à la
        maladie. Les garder reviendrait à faire passer une reconnaissance de chaîne de
        caractères pour un périmètre déclaré.
        """
        assert {"185086009", "87433001"} <= set(ECARTES)

    def test_chaque_pathologie_porte_son_article(self) -> None:
        assert all(patho.article for patho in PATHOLOGIES)

    def test_chaque_pathologie_a_au_moins_un_code(self) -> None:
        """Une pathologie sans code ne s'apparierait jamais, et rien ne le dirait."""
        assert all(patho.codes for patho in PATHOLOGIES)

    def test_chaque_code_porte_un_fondement(self) -> None:
        """La propriété qui empêche le glissement de recommencer.

        Un code sans fondement est un jugement clinique posé sans source. Le test échoue
        avant que la ligne n'atteigne le dépôt.
        """
        for patho in PATHOLOGIES:
            for declare in patho.codes:
                assert declare.fondement.strip(), f"{patho.identifiant} / {declare.code}"

    def test_chaque_pathologie_cite_le_champ_de_son_guide(self) -> None:
        """Le champ est repris du guide, pas reformulé — c'est lui qui fait autorité."""
        for patho in PATHOLOGIES:
            assert patho.guide.champ.strip()
            assert patho.guide.url.startswith("https://www.has-sante.fr/")

    def test_aucun_code_n_est_declare_deux_fois(self) -> None:
        """Un même code sous deux pathologies rendrait l'appariement dépendant de l'ordre."""
        vus = [declare.code for patho in PATHOLOGIES for declare in patho.codes]
        assert len(vus) == len(set(vus))

    def test_l_appariement_ne_repose_que_sur_la_liste_declaree(self) -> None:
        """Un code hors liste ne s'apparie pas, quelle que soit sa parenté clinique."""
        assert pathologie(SYSTEME_SNOMED, "13645005") is not None
        assert pathologie(SYSTEME_SNOMED, "444814009") is None
        assert pathologie(SYSTEME_SNOMED, "185086009") is None, "écarté après interrogation"


class TestAppariement:
    def test_seules_les_conditions_actives_sont_appariees(self) -> None:
        contexte = _contexte(("44054006", "active"), ("88805009", "resolved"))
        apparies = apparier(contexte)
        assert set(apparies) == {"diabete"}

    def test_un_generique_et_son_descendant_menent_au_meme_gabarit(self) -> None:
        descendant = apparier(_contexte(("88805009", "active")))
        generique = apparier(_contexte(("84114007", "active")))
        assert set(descendant) == set(generique) == {"insuffisance_cardiaque"}

    def test_deux_codes_d_une_meme_pathologie_ne_font_qu_un_gabarit(self) -> None:
        apparies = apparier(_contexte(("44054006", "active"), ("368581000119106", "active")))
        assert set(apparies) == {"diabete"}
        assert len(apparies["diabete"]) == 2


def _patho(code: str) -> Pathologie:
    """La pathologie d'un code du périmètre, dont l'absence serait une erreur du test."""
    trouvee = pathologie(SYSTEME_SNOMED, code)
    assert trouvee is not None, code
    return trouvee


class TestFormulation:
    def test_la_forme_phrasee_est_interrogative(self) -> None:
        question = texte(_patho("44054006"), Forme.PRISE_EN_CHARGE)
        assert question.endswith("?")
        assert "diabète de type 2" in question

    def test_la_forme_nue_est_le_libelle_seul(self) -> None:
        assert texte(_patho("44054006"), Forme.LIBELLE) == "diabète de type 2"

    def test_deux_formes_de_la_meme_pathologie_different(self) -> None:
        """Sans quoi la mesure des formulations comparerait deux fois la même phrase."""
        patho = _patho("44054006")
        assert texte(patho, Forme.LIBELLE) != texte(patho, Forme.PRISE_EN_CHARGE)

    def test_aucune_formulation_n_est_imperative(self) -> None:
        """Sur **toutes** les formulations candidates, y compris celles ajoutées plus tard."""
        for patho in PATHOLOGIES:
            for forme in Forme:
                assert not any(mot in texte(patho, forme).lower() for mot in IMPERATIFS)

    def test_chaque_forme_a_son_gabarit(self) -> None:
        """Une forme déclarée sans gabarit lèverait à la formulation, pas ici."""
        assert set(FORMULATIONS) == set(Forme)

    def test_les_articles_sont_corrects(self) -> None:
        """« du bronchopneumopathie » est ce qu'une heuristique aurait produit."""
        assert "du diabète" in texte(_patho("44054006"), Forme.PRISE_EN_CHARGE)
        assert "de l'insuffisance" in texte(_patho("84114007"), Forme.PRISE_EN_CHARGE)
        assert "de la bronchopneumopathie" in texte(_patho("13645005"), Forme.PRISE_EN_CHARGE)

    def test_chaque_formulation_est_rendue_mot_pour_mot(self) -> None:
        """Le rendu réel de chaque gabarit, figé.

        Deux fautes de français ont déjà été écrites ici — « du  diabète » et « sur
        insuffisance cardiaque ». Aucune n'aurait échoué à un test de forme générale ; il
        faut lire les phrases.
        """
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
        bpco = _patho("13645005")
        for forme, attendu in attendus.items():
            assert texte(bpco, forme) == attendu

    def test_aucune_formulation_ne_porte_d_espace_double(self) -> None:
        for patho in PATHOLOGIES:
            for forme in Forme:
                assert "  " not in texte(patho, forme)


class TestFormeLibre:
    def test_elle_n_accorde_aucun_article(self) -> None:
        """Elle reçoit un libellé quelconque, dont aucune heuristique ne déduit le genre.

        Le deux-points contourne le problème au lieu de le deviner.
        """
        attendu = "que publie la Haute Autorité de Santé sur : anémie ?"
        assert question_libre("anémie") == attendu

    def test_elle_n_est_pas_imperative(self) -> None:
        for libelle in ("anémie", "sinusite chronique", "AVC - accident vasculaire cérébral"):
            assert not any(mot in question_libre(libelle).lower() for mot in IMPERATIFS)

    def test_elle_ne_porte_pas_d_espace_double(self) -> None:
        assert "  " not in question_libre("  anémie  ")
