# Le périmètre, et d'où il vient

Trois pathologies, cinq codes SNOMED CT, trois exclusions. Ce document dit sur quoi chaque
ligne de `src/passerelle/requete/perimetre.py` repose.

Il existe parce que la première version n'avait pas de réponse à cette question. Les codes
avaient été retenus sur la foi des libellés anglais rendus par le serveur FHIR du bac à
sable : un appariement de chaînes de caractères présenté comme un périmètre déclaré.

## Le champ vient des guides, cité

Les guides de parcours de la Haute Autorité de Santé énoncent eux-mêmes ce qu'ils couvrent.
C'est cette phrase qui fixe le périmètre — pas une reformulation.

| pathologie | guide | champ déclaré |
| --- | --- | --- |
| diabète de type 2 | [Parcours de soins du patient adulte vivant avec un diabète de type 2](https://www.has-sante.fr/jcms/p_3634754/), juillet 2025 | « les soins, l'accompagnement et le suivi global de l'adulte vivant avec un diabète de type 2 » |
| insuffisance cardiaque | [Guide du parcours de soins « Insuffisance cardiaque »](https://www.has-sante.fr/jcms/c_1242988/), février 2012, actualisé juin 2014 | « le parcours de soins d'une personne ayant une insuffisance cardiaque (IC) **chronique** » |
| BPCO | [Guide du parcours de soins « Bronchopneumopathie chronique obstructive »](https://www.has-sante.fr/jcms/c_1242507/), actualisation 2019 | « son champ concerne **toutes les formes de la BPCO**, des stades léger et modéré au stade sévère » |

**Un guide raisonne en stades de sévérité et en formes cliniques, jamais en codes.** Le
passage de l'un aux autres reste un pas, et le champ `fondement` de chaque code dit lequel
a été franchi : le champ du guide, ou la définition du concept SNOMED.

## Les exclusions, et ce qui les fonde

Deux codes de la BPCO figuraient au périmètre sans autre justification que leur libellé.
Le corpus de la HAS a été interrogé sur chacun — `uv run sonde-perimetre`, relevé complet
dans [`perimetre_releve.md`](perimetre_releve.md). Le critère d'acceptation avait été
déclaré **avant** la mesure, dans les questions de la sonde.

**`185086009` bronchite chronique obstructive.** Aucun passage ne la rattache à la BPCO.
Les deux seuls qui les font voisiner sont des tableaux d'indications de médicaments, où
« asthme **ou** bronchite chronique obstructive » est un libellé d'autorisation de mise sur
le marché. Et les indicateurs de qualité du parcours disent l'inverse de ce qu'il fallait :
il faut « penser à la BPCO […] devant le suivi d'une bronchite chronique ». C'est une
relation de suspicion — ce qui suppose que ce n'en est pas une.

**`87433001` emphysème pulmonaire.** La synthèse HAS sur la prescription d'activité physique
décrit la BPCO comme « souvent associée à des lésions parenchymateuses pulmonaires
(emphysème) » : une association, pas une appartenance. Le guide range par ailleurs
l'emphysème parmi les choses à rechercher au scanner chez un patient déjà atteint, et une
liste de vaccination l'énumère comme entité distincte de la bronchopneumopathie obstructive.

Une lecture généreuse aurait pu sauver l'emphysème. Elle est écartée parce que le critère
était fixé d'avance — c'est à cela que sert de le déclarer.

**`15777000` prédiabète.** Le guide 2025 lui consacre un chapitre de prévention : ce n'est
donc pas lui qui est hors champ. C'est le prédiabétique qui n'a pas de diabète de type 2, et
c'est du diabète de type 2 que la question est posée.

## Ce que ces exclusions coûtent

La BPCO n'a plus que son code générique `13645005`, absent des données observées —
mesuré : sur les trente-sept codes distincts des cinq patients de démonstration, trois
seulement s'apparient au périmètre, et aucun n'est celui-là.
**Aucun patient de démonstration ne déclenche plus la question sur la BPCO.** Le gabarit et
sa réponse enregistrée restent en place, et un serveur employant le code générique
l'activerait.

**Et le cas à deux requêtes disparaît avec elles.** Mesuré par `sonde-dossiers` : le bac à
sable ne porte que quatre dossiers cumulant diabète et insuffisance cardiaque, et les quatre
sont ceux de patients décédés — Synthea modélise la trajectoire complète, et ce cumul
l'abrège. Aucun patient vivant n'en porte deux.

La démonstration n'exerce donc plus le chemin à plusieurs interrogations, celui-là même où
vivait le défaut du journal qui attribuait à une question les passages de la précédente. Il
reste couvert par les tests ; il n'est plus montré.

C'est un appauvrissement réel de la démonstration. Il est préféré à un périmètre plus large
dont personne ne pourrait dire d'où il vient.

## Ce qui reste ouvert

- `368581000119106` est fondé sur **le nom du concept** — « due to type 2 diabetes
  mellitus », dont « dû à » présuppose la maladie — et sur le dépistage des neuropathies que
  le guide 2025 prévoit chez le patient diabétique. C'est une lecture de libellé : le
  fondement le plus faible des cinq, et le dire en fait partie.
- Aucun de ces codes n'a été relu par un clinicien. Le fondement rend chaque ligne
  contestable ligne à ligne ; il ne la valide pas.

## Les relevés qui ne sont pas ici

`sonde-terminologie` et `sonde-libre` produisent des relevés que ce dépôt **ne publie pas**.
Ils apparient des codes à leurs désignations françaises, ce qui en fait un « Dérivé » au sens
de la licence d'affiliation SNOMED CT, dont la distribution est interdite. Les commandes sont
dans le README ; les relevés se produisent en local, avec la clé de qui les lance.

Ce qui est publié ici — les codes, leur fondement, les passages de la HAS — n'en dépend pas :
le périmètre se justifie par les guides, jamais par un libellé.

## Attribution

Les passages cités proviennent des publications de la Haute Autorité de Santé, diffusées
sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/).

Les identifiants SNOMED CT figurent sans leurs libellés : la licence d'affiliation réserve
la diffusion du contenu terminologique aux utilisateurs autorisés.
