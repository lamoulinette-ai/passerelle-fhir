#!/usr/bin/env bash
#
# Déploiement de la passerelle, lancé par la chaîne d'intégration via SSH.
#
# Ce script est la SEULE chose que la clé de déploiement peut exécuter : l'entrée
# correspondante d'`authorized_keys` porte `restrict,command="/opt/passerelle-fhir/deployer.sh"`.
# Une clé compromise permet donc de redéployer ce service, et rien d'autre.
#
# `SSH_ORIGINAL_COMMAND` est délibérément ignorée. La lire reviendrait à rendre à l'appelant
# le shell que la commande forcée lui retire.
#
# Installation : copier dans /opt/passerelle-fhir/, propriété du compte de déploiement,
# `chmod 700`.

set -euo pipefail

DOSSIER=/opt/passerelle-fhir
SANTE=http://127.0.0.1:8006/health
IMAGE=ghcr.io/lamoulinette-ai/passerelle-fhir:latest
CONTENEUR=passerelle-api
ATTENTE=30

cd "$DOSSIER"

# L'image en service avant la mise à jour. Sans elle, une image cassée laisserait le service
# par terre jusqu'à la prochaine correction — vingt minutes au lieu de trente secondes.
precedente="$(docker inspect --format '{{.Image}}' "$CONTENEUR" 2>/dev/null || true)"

echo "--- mise à jour du dépôt ---"
# `--ff-only` : une divergence doit échouer bruyamment, jamais produire une fusion muette
# dans un dossier que personne ne relit.
git pull --ff-only

echo "--- image et démarrage ---"
docker compose pull
docker compose up -d

echo "--- vérification (${ATTENTE}s au plus) ---"
for _ in $(seq "$ATTENTE"); do
    if curl -fsS --max-time 2 "$SANTE" >/dev/null 2>&1; then
        echo "le service répond"
        curl -fsS "$SANTE"
        echo
        docker compose ps
        exit 0
    fi
    sleep 1
done

echo "AUCUNE RÉPONSE après ${ATTENTE}s" >&2

if [ -z "$precedente" ]; then
    echo "aucune image précédente connue — pas de retour possible" >&2
    docker compose logs --tail 40 api >&2
    exit 1
fi

echo "--- retour à l'image précédente ---" >&2
docker tag "$precedente" "$IMAGE"
docker compose up -d

for _ in $(seq "$ATTENTE"); do
    if curl -fsS --max-time 2 "$SANTE" >/dev/null 2>&1; then
        echo "retour effectué, le service répond de nouveau" >&2
        # Sortie en échec malgré le service rétabli : la chaîne doit rougir, sinon une
        # image cassée passerait pour un déploiement réussi.
        exit 1
    fi
    sleep 1
done

echo "le retour n'a pas rétabli le service" >&2
docker compose logs --tail 40 api >&2
exit 1
