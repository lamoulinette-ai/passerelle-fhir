"""Sondes d'observation — ce qu'un serveur annonce, et ce qu'il applique.

La configuration est chargée à l'import du paquet, et non dans chaque `main()` : les sondes
sont sept, elles le seront davantage, et une seule d'entre elles qui oublierait l'appel
repartirait avec les valeurs par défaut sans que rien ne le dise.
"""

from passerelle import environnement

environnement.charger()
