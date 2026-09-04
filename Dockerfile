# Image de la passerelle. Beaucoup plus légère que celle du documentaliste : aucun modèle,
# aucun poids à cuire, aucune dépendance native lourde — httpx, pydantic et FastAPI.
#
# Les réponses de secours voyagent dans le paquet et non à côté : le mode dégradé doit
# fonctionner dans l'image, pas seulement depuis un clone.

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Les dépendances d'abord, le code ensuite : une modification du code ne réinstalle rien.
COPY pyproject.toml uv.lock* ./
RUN uv sync --extra api --no-install-project --no-dev

COPY src/ ./src/
RUN uv sync --extra api --no-dev

# Utilisateur non privilégié. Le conteneur tourne en lecture seule et n'écrit que dans le
# tmpfs monté sur /tmp par le compose.
RUN useradd --system --uid 10001 --no-create-home passerelle \
    && chown -R passerelle:passerelle /app
USER passerelle

EXPOSE 8006

# Un seul processus : l'état des sessions et le registre des traces vivent en mémoire, et
# plusieurs travailleurs les cloisonneraient sans que rien ne le signale.
CMD ["uvicorn", "passerelle.api.app:app", "--host", "0.0.0.0", "--port", "8006", "--workers", "1"]
