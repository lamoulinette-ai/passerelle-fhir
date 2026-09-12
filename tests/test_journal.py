"""Ce que la trace doit prouver, et ce qu'elle ne doit jamais porter.

Cinq propriétés valent tous les autres tests de ce fichier :

- **deux questions posées produisent deux interrogations distinctes**, chacune avec ses
  propres passages. Un modèle à champ unique a déjà attribué les passages d'une question à
  la suivante, et aucun test ne l'a vu parce qu'aucun n'en posait deux ;
- **une exécution dégradée produit une trace qui nomme sa cause**, jamais une trace vide ;
- **les deux frontières de confiance ne se confondent pas** — une lecture faite avec la clé
  de service ne doit jamais être étiquetée comme une autorisation déléguée ;
- **la trace distingue ce qui a été vu de ce qui a été retenu** — c'est la seule sélection
  que la passerelle opère elle-même ;
- **aucune donnée d'identification n'est représentable**, et la contrainte est plus stricte
  que pour le contexte, puisque les traces sont exportées.
"""

from __future__ import annotations

import json

from passerelle.journal.schemas import Frontiere, Mode
from passerelle.journal.tenue import Registre, Tenue, exporter


def _trace_complete() -> Tenue:
    tenue = Tenue(mode=Mode.SMART, contexte_patient="Patient/2cda5aad")
    tenue.autorise(["patient/Patient.read", "patient/Condition.read"])
    tenue.lecture(
        "Patient/2cda5aad",
        "serveur FHIR",
        Frontiere.DELEGUEE,
        autorisation="patient/Patient.read",
    )
    tenue.probleme(
        "http://snomed.info/sct",
        "44054006",
        libelle_source="Diabetes",
        libelle_fr="diabète de type 2",
        terminologie="SNOMED CT",
        version="2026-03",
        statut="active",
        dans_le_perimetre=True,
    )
    tenue.probleme(
        "http://snomed.info/sct", "15777000", libelle_source="Prediabetes", statut="active"
    )
    interrogation = tenue.interroger("diabete", "quel parcours de soins… ?", ["44054006"])
    tenue.repondue(interrogation, "reponse")
    tenue.passage(interrogation, 1, "has_1234", 12, "Guide parcours de soins")
    tenue.passage(interrogation, 2, "has_1234", 48, "Guide parcours de soins")
    return tenue


class TestInterrogations:
    def test_deux_questions_produisent_deux_interrogations(self) -> None:
        """Le défaut trouvé à l'essai réel : un champ unique perdait la première question."""
        tenue = Tenue()
        premiere = tenue.interroger("diabete", "question diabète", ["44054006"])
        tenue.passage(premiere, 1, "has_diabete", 1, "Parcours diabète")
        seconde = tenue.interroger("bpco", "question BPCO", ["185086009"])
        tenue.passage(seconde, 1, "has_bpco", 1, "Parcours BPCO")

        trace = tenue.close()
        assert [i.gabarit for i in trace.interrogations] == ["diabete", "bpco"]
        assert [i.question for i in trace.interrogations] == ["question diabète", "question BPCO"]

    def test_aucun_passage_ne_traverse_d_une_question_a_l_autre(self) -> None:
        tenue = Tenue()
        premiere = tenue.interroger("diabete", "q1")
        tenue.passage(premiere, 1, "has_diabete", 1)
        seconde = tenue.interroger("bpco", "q2")
        tenue.passage(seconde, 1, "has_bpco", 1)

        trace = tenue.close()
        assert [p.document for p in trace.interrogations[0].passages] == ["has_diabete"]
        assert [p.document for p in trace.interrogations[1].passages] == ["has_bpco"]

    def test_les_passages_du_meme_document_restent_distincts(self) -> None:
        """Cinq extraits d'un guide ne sont pas cinq guides : le numéro et la page les séparent."""
        trace = _trace_complete().close()
        passages = trace.interrogations[0].passages
        assert len(passages) == 2
        assert {p.document for p in passages} == {"has_1234"}
        assert [p.page for p in passages] == [12, 48]

    def test_les_defauts_du_moteur_sont_rattaches_a_leur_question(self) -> None:
        tenue = Tenue()
        interrogation = tenue.interroger("diabete", "q")
        tenue.repondue(interrogation, "reponse", defauts=["citation hors périmètre"])
        assert tenue.close().interrogations[0].defauts == ["citation hors périmètre"]

    def test_une_interrogation_indisponible_est_consignee(self) -> None:
        tenue = Tenue()
        tenue.repondue(tenue.interroger("bpco", "q"), "indisponible")
        assert tenue.close().interrogations[0].issue == "indisponible"

    def test_aucune_question_posee_rend_une_liste_vide(self) -> None:
        assert Tenue().close().interrogations == []


class TestProblemes:
    def test_la_trace_consigne_tous_les_problemes_lus(self) -> None:
        """Aucun n'est écarté : la trace doit les porter tous, quelle que soit la formulation."""
        trace = _trace_complete().close()
        assert {p.code for p in trace.problemes} == {"44054006", "15777000"}

    def test_la_trace_dit_quelle_formulation_chaque_probleme_aurait(self) -> None:
        """Le drapeau ne sélectionne rien ; il annonce une tournure mesurée ou libre."""
        trace = _trace_complete().close()
        mesures = [p for p in trace.problemes if p.dans_le_perimetre]
        libres = [p for p in trace.problemes if not p.dans_le_perimetre]
        assert [p.code for p in mesures] == ["44054006"]
        assert [p.code for p in libres] == ["15777000"]

    def test_le_statut_clinique_est_conserve(self) -> None:
        assert all(p.statut == "active" for p in _trace_complete().close().problemes)

    def test_le_taux_de_resolution_se_calcule(self) -> None:
        assert _trace_complete().close().taux_de_resolution == 0.5

    def test_sans_probleme_le_taux_est_indetermine(self) -> None:
        """Aucun code à résoudre n'est pas un taux de zéro."""
        assert Tenue().close().taux_de_resolution is None


class TestFrontieres:
    def test_les_deux_frontieres_coexistent_sans_se_confondre(self) -> None:
        tenue = Tenue()
        tenue.lecture("Patient/1", "serveur FHIR", Frontiere.DELEGUEE, "patient/Patient.read")
        tenue.lecture("POST /question", "documentaliste", Frontiere.SERVICE, "clé de service")
        trace = tenue.close()

        deleguees = [a for a in trace.acces if a.frontiere is Frontiere.DELEGUEE]
        services = [a for a in trace.acces if a.frontiere is Frontiere.SERVICE]
        assert len(deleguees) == 1 and len(services) == 1
        assert services[0].origine == "documentaliste"

    def test_une_lecture_anonyme_se_dit(self) -> None:
        """Le mode démonstration lit sans jeton : la trace ne doit pas laisser croire l'inverse."""
        tenue = Tenue(mode=Mode.DEMONSTRATION)
        tenue.lecture("Patient/1", "serveur FHIR", Frontiere.AUCUNE)
        trace = tenue.close()
        assert trace.acces[0].frontiere is Frontiere.AUCUNE
        assert trace.scopes_accordes == []


class TestDegradation:
    def test_une_trace_degradee_nomme_sa_cause(self) -> None:
        tenue = Tenue()
        tenue.degradation("clé SMT absente", "codes affichés bruts")
        trace = tenue.close()
        assert trace.degrade
        assert trace.degradations[0].cause == "clé SMT absente"
        assert trace.degradations[0].consequence

    def test_une_trace_normale_n_est_pas_degradee(self) -> None:
        assert not _trace_complete().close().degrade

    def test_plusieurs_degradations_coexistent(self) -> None:
        tenue = Tenue()
        tenue.degradation("clé SMT absente", "codes bruts")
        tenue.degradation("API documentaliste injoignable", "réponses enregistrées")
        assert len(tenue.close().degradations) == 2


class TestDecisions:
    def test_un_refus_propre_est_consigne(self) -> None:
        """Ce que le serveur amont laisse passer et que la passerelle refuse n'a
        aucune trace ailleurs qu'ici."""
        tenue = Tenue(mode=Mode.SMART, contexte_patient="Patient/2cda5aad")
        tenue.refus("Patient/ecaea95c", "hors du contexte patient du jeton")
        assert tenue.close().decisions[0].motif


class TestExport:
    def test_l_export_est_du_json(self) -> None:
        charge = json.loads(exporter(_trace_complete().close()))
        assert charge["mode"] == "SMART"
        assert len(charge["interrogations"]) == 1

    def test_l_ordre_des_champs_est_stable(self) -> None:
        """Deux traces doivent se comparer ligne à ligne, donc les clés sont triées."""
        charge = json.loads(exporter(_trace_complete().close()))
        rendu = exporter(_trace_complete().close())
        positions = [rendu.index(f'"{cle}"') for cle in charge]
        assert positions == sorted(positions)
        assert list(charge) == sorted(charge)

    def test_la_trace_ne_porte_aucune_identite(self) -> None:
        rendu = exporter(_trace_complete().close())
        for interdit in ("Stanton", "Stewart", "999-78-9632", "Schowalter", "555-164"):
            assert interdit not in rendu


class TestRegistre:
    def test_les_dernieres_arrivent_en_tete(self) -> None:
        registre = Registre()
        for _ in range(3):
            registre.deposer(Tenue().close())
        assert registre.dernieres()[0].identifiant == list(registre)[-1].identifiant

    def test_la_memoire_est_bornee(self) -> None:
        """Sans borne, un service qui tourne longtemps finirait par manquer de mémoire."""
        registre = Registre(memoire=2)
        for _ in range(5):
            registre.deposer(Tenue().close())
        assert len(registre) == 2

    def test_une_trace_se_retrouve_par_son_identifiant(self) -> None:
        registre = Registre()
        trace = Tenue().close()
        registre.deposer(trace)
        assert registre.par_identifiant(trace.identifiant) is trace

    def test_un_identifiant_inconnu_rend_none(self) -> None:
        assert Registre().par_identifiant("absent") is None

    def test_le_registre_se_vide(self) -> None:
        registre = Registre()
        registre.deposer(Tenue().close())
        registre.vider()
        assert len(registre) == 0
