# Passerelle FHIR — contexte patient et recherche documentée

Un dossier patient au format **FHIR R4**. Son contexte clinique codé, extrait puis résolu
contre le serveur de terminologies de l'Agence du Numérique en Santé. Une interrogation du
corpus des publications de la **Haute Autorité de Santé**, dont chaque affirmation cite
l'extrait qui la fonde — ou un refus, quand le corpus ne répond pas.

> **Démonstrateur technique sur données synthétiques.** Outil de recherche documentaire : il
> ne constitue ni un dispositif médical, ni un outil d'aide au diagnostic ou à la décision
> thérapeutique.

---

## La ligne à ne pas franchir

**Outil de recherche documentaire contextualisée. Ni diagnostic, ni recommandation
thérapeutique, ni orientation de prise en charge.**

Un système d'aide à la décision clinique relève du dispositif médical au sens du règlement
MDR 2017/745 et du haut risque au sens de l'AI Act. Un moteur qui restitue des passages
sourcés d'un référentiel public, sans les interpréter ni les appliquer à un cas, n'en relève
pas.

Cinq règles de conception matérialisent cette ligne :

1. La sortie est toujours un **extrait sourcé**, jamais une phrase qui conclurait à la place
   du soignant.
2. Aucune formulation impérative.
3. **Données synthétiques uniquement** — jamais de données réelles, même anonymisées.
4. **C'est l'utilisateur qui désigne la condition, jamais la passerelle.** Toutes les
   conditions lues sont interrogeables ; le périmètre déclaré ne trie pas ce qui mériterait
   une question — trier ce qui est *cliniquement pertinent* dans un dossier serait
   précisément l'interprétation que la règle 1 interdit. Il distingue seulement les
   conditions dont la formulation a été mesurée contre le corpus de celles qui partent sur
   une question libre.
5. **Chaque code déclaré porte sa source**, et un test refuse celui qui n'en a pas. Le champ
   de chaque pathologie est repris mot pour mot du guide de parcours de la HAS ; les codes
   qu'aucune source ne rattachait à leur maladie ont été écartés après interrogation du
   corpus. Voir [`docs/perimetre.md`](docs/perimetre.md).

Une conséquence est assumée plutôt que masquée : le périmètre de la BPCO se réduit à son code
générique, absent des données de démonstration. **Aucun dossier enregistré ne porte de BPCO** —
sa formulation mesurée ne se voit qu'en connectant un serveur. Un périmètre plus large aurait
fait meilleure impression sans que personne puisse dire d'où il venait.


## Ce que la passerelle retient d'un dossier

Un dossier FHIR porte le nom, l'adresse, le téléphone, le numéro de sécurité sociale, le
permis de conduire et le passeport du patient. **Aucun de ces champs n'a de représentation
dans le modèle interne** — une requête documentaire n'en a pas l'usage, et un modèle qui les
transporterait finirait par les journaliser.

Ce qui est retenu : l'identifiant de la ressource, le sexe, les dates de naissance et de
décès, et les problèmes codés avec leur statut clinique.

## Mise en route

```bash
uv sync
uv run pytest
uv run uvicorn passerelle.api.app:app --port 8006
```

**La suite de tests ne touche pas au réseau** — transports simulés et ressources
enregistrées. C'est une propriété tenue, pas une commodité : la chaîne d'intégration ne
reçoit aucun secret, si bien qu'un test qui appellerait un service extérieur échouerait.

**Vérification** — les trois, jamais l'une sans les autres :

```bash
uv run ruff check src/ tests/ ; uv run ruff format --check src/ tests/ ; uv run pytest
```

## Les sondes

Sept commandes mesurent ce qui n'a pas à être supposé : ce qu'un serveur FHIR applique
vraiment (`sonde-conformite`), quelle formulation obtient une réponse du corpus
(`sonde-formulations`), quelle part des codes obtient un libellé français
(`sonde-terminologie`), ce que le corpus répond quand on lui demande de fonder le périmètre
(`sonde-perimetre`), ce qu'il rend sur une condition quelconque désignée hors périmètre
(`sonde-libre`), quels dossiers du bac à sable portent une pathologie déclarée
(`sonde-dossiers`), et ce que les deux bacs à sable d'éditeur rendent possible
(`sonde-oracle`).

**`sonde-oracle` prend ses identifiants de patients en argument**, là où `sonde-dossiers` les
découvre. Ce n'est pas une négligence : sur Oracle Millennium, `Condition` exige `patient`,
`subject` ou `_id`, et une recherche par code y est impossible. La liste ne peut venir que
des patients de test publiés par l'éditeur.

Chacune accepte `--json` et `--sortie CHEMIN`. **Employer `--sortie` plutôt qu'une
redirection** : les relevés portent des caractères que la console Windows ne sait pas
écrire, et une redirection perd alors un relevé déjà obtenu.

```bash
uv run sonde-terminologie --sortie docs/terminologie_releve.md
```

## Configuration

Copier `.env.example` en `.env`. Le serveur FHIR interrogé par défaut est le point d'entrée
R4 du [SMART App Launcher](https://launch.smarthealthit.org), dont les patients d'exemple
sont dérivés de [Synthea](https://synthetichealth.github.io/synthea/).

## Terminologie et licence

La résolution des codes s'appuie sur le [Serveur Multi-Terminologies](https://smt.esante.gouv.fr/)
de l'Agence du Numérique en Santé, qui expose un service FHIR de terminologie. `$lookup` y
répond **sans authentification** — mesuré depuis deux machines et deux réseaux — et la
passerelle n'envoie donc aucune identification.

Une **affiliation SNOMED CT** au centre national français reste requise, et gratuite : c'est
elle qui rend l'usage licite, indépendamment de toute clé technique.

**Ce dépôt ne redistribue aucun contenu SNOMED CT.** La licence d'affiliation réserve l'accès
à la terminologie aux utilisateurs autorisés et impose un registre nominatif des
sous-licenciés : un dépôt public ne peut satisfaire ni l'un ni l'autre. Les identifiants de
concepts circulent dans les données patients ; les libellés sont résolus à l'exécution, avec
la clé de l'utilisateur.

En l'absence de clé, la passerelle affiche les codes bruts et le journal nomme la cause.

## Licence et sources

Le code est sous [licence Apache 2.0](LICENSE). Les attributions dues aux tiers sont
rassemblées dans [`NOTICE`](NOTICE), qui doit suivre toute redistribution.

> Ce matériel comprend la version nationale française de la SNOMED Clinical Terms®
> (SNOMED CT®) qui est utilisée avec l'autorisation de l'Agence du Numérique en Santé.
> Tous droits réservés.
>
> Ce matériel comprend la SNOMED Clinical Terms® (SNOMED CT®) qui est utilisée avec
> l'autorisation de l'International Health Terminology Standards Development Organisation
> (IHTSDO). Tous droits réservés. SNOMED CT® a été à l'origine créée par le College of
> American Pathologists. « SNOMED » et « SNOMED CT » sont des marques déposées de l'IHTSDO.
>
> Édition nationale française — Juin 2026 v1.0, publiée le 21 juin 2026
> (version 20260621, module 11000315107).

Corpus HAS sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/),
attribution : Haute Autorité de Santé. Données patients synthétiques, dérivées de
[Synthea](https://synthetichealth.github.io/synthea/).
