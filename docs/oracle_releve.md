**Bac à sable ouvert — dossiers lus sans autorisation**

| identifiant | sexe | âge | vivant | conditions |
| --- | --- | ---: | :---: | ---: |
| `12743119` | male | 80 | oui | 146 |
| `12746484` | female | 69 | oui | 169 |
| `12742497` | female | 54 | oui | 22 |

**Bac à sable sécurisé — jeton demandé sans contexte patient**

- portées demandées : `user/Patient.read user/Condition.read openid fhirUser`
- portées accordées : `fhirUser openid user/Condition.read user/Patient.read`
- contexte patient du jeton : `aucun`

| dossier désigné | `Patient` | `Condition` |
| --- | --- | ---: |
| `12743119` | lu | 154 |
| `12746484` | lu | 171 |
| `12742497` | lu | 29 |

Un jeton **sans contexte patient** qui lit malgré tout le dossier désigné rend possible un parcours où la page présente la liste. S'il refuse, le serveur applique ses portées — ce qui est la posture annoncée, et ferme cette voie.