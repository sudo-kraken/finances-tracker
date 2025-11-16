FROM ghcr.io/astral-sh/uv:0.9-python3.13-bookworm-slim@sha256:17411163b764cafed659e542d81c59f402833874b70faaf01785f21f1ba2922b

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATABASE_FOLDER=/app/db
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos "" --home /nonroot --uid 10001 appuser

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

RUN chown -R appuser:appuser /app
USER appuser

ENV PORT=7070
    
EXPOSE 7070

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1
  
CMD ["sh", "-c", "uv run gunicorn -w 2 -b 0.0.0.0:${PORT:-7070} app:app"]
