# Passerelle FHIR — contexte patient et recherche documentée

Un dossier patient au format **FHIR R4**. Son contexte clinique codé, extrait puis résolu
contre le serveur de terminologies de l'Agence du Numérique en Santé. Une interrogation du
corpus des publications de la **Haute Autorité de Santé**, dont chaque affirmation cite
l'extrait qui la fonde — ou un refus, quand le corpus ne répond pas.

> **En construction.** Le bloc de lecture FHIR est en place ; la résolution terminologique,
> l'autorisation SMART on FHIR et le journal de traçabilité ne le sont pas encore.

---

## La ligne à ne pas franchir

**Outil de recherche documentaire contextualisée. Ni diagnostic, ni recommandation
thérapeutique, ni orientation de prise en charge.**

Un système d'aide à la décision clinique relève du dispositif médical au sens du règlement
MDR 2017/745 et du haut risque au sens de l'AI Act. Un moteur qui restitue des passages
sourcés d'un référentiel public, sans les interpréter ni les appliquer à un cas, n'en relève
pas.

Quatre règles de conception matérialisent cette ligne :

1. La sortie est toujours un **extrait sourcé**, jamais une phrase qui conclurait à la place
   du soignant.
2. Aucune formulation impérative.
3. **Données synthétiques uniquement** — jamais de données réelles, même anonymisées.
4. **La sélection des conditions est déclarée, pas déduite.** Une liste fixe de codes ; une
   condition compte si elle y figure. Trier ce qui est *cliniquement pertinent* dans un
   dossier serait précisément l'interprétation que la règle 1 interdit.

## Ce que la passerelle retient d'un dossier

Un dossier FHIR porte le nom, l'adresse, le téléphone, le numéro de sécurité sociale, le
permis de conduire et le passeport du patient. **Aucun de ces champs n'a de représentation
dans le modèle interne** — une requête documentaire n'en a pas l'usage, et un modèle qui les
transporterait finirait par les journaliser.

Ce qui est retenu : l'identifiant de la ressource, le sexe, les dates de naissance et de
décès, et les problèmes codés avec leur statut clinique.

## Mise en route

```bash
uv sync --extra api
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

## Configuration

Copier `.env.example` en `.env`. Le serveur FHIR interrogé par défaut est le point d'entrée
R4 du [SMART App Launcher](https://launch.smarthealthit.org), dont les patients d'exemple
sont dérivés de [Synthea](https://synthetichealth.github.io/synthea/).

## Terminologie et licence

La résolution des codes s'appuie sur le [Serveur Multi-Terminologies](https://smt.esante.gouv.fr/)
de l'Agence du Numérique en Santé, qui expose un service FHIR de terminologie. Elle suppose
une **clé d'API personnelle** et une **affiliation SNOMED CT** au centre national français —
l'une et l'autre gratuites.

**Ce dépôt ne redistribue aucun contenu SNOMED CT.** La licence d'affiliation réserve l'accès
à la terminologie aux utilisateurs autorisés et impose un registre nominatif des
sous-licenciés : un dépôt public ne peut satisfaire ni l'un ni l'autre. Les identifiants de
concepts circulent dans les données patients ; les libellés sont résolus à l'exécution, avec
la clé de l'utilisateur.

En l'absence de clé, la passerelle affiche les codes bruts et le journal nomme la cause.

## Licence et sources

Corpus HAS sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/).
Données patients synthétiques, dérivées de Synthea.
