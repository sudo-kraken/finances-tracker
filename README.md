# Finances Tracker

Small Flask application for tracking monthly finances. SQLite by default, easy to switch to any SQLAlchemy database.

## Features
- Username and password sign in via Flask-Login
- Monthly workspaces with accounts, bills and incomes
- Proper Decimal handling
- Clean `app:app` entrypoint for Flask and Gunicorn
- `/health` endpoint
- Reproducible setup with uv, optional Docker
- Tests with high coverage

## Requirements
- Python 3.13 with [uv](https://docs.astral.sh/uv/)  # set to 3.10 if you prefer to keep current target
- Docker optional

## Quick start with uv
```bash
uv sync --all-extras
uv run flask --app app:app run --host 0.0.0.0 --port ${PORT:-7070}
# or Gunicorn
uv run --no-dev gunicorn -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:${PORT:-7070} app:app
```

## Docker
```bash
docker run --rm -e PORT=7070 -p 7070:7070 ghcr.io/sudo-kraken/finances-tracker:latest

# For compose use see the repo example
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| PORT | no | 7070 | Port to bind |
| WEB_CONCURRENCY | no | 2 | Gunicorn workers |
| SECRET_KEY | yes in production |  | Flask secret key |
| SQLALCHEMY_DATABASE_URI | no | sqlite:///app/db/finances.db | Database URI |
| FINANCES_TESTING | no | 0 | Enables test configuration |

## Health and readiness
- `GET /health` returns `{ "ok": true }`.

## Project layout
```
finances-tracker/
  app/
  templates/
  static/
  Dockerfile
  pyproject.toml
  tests/
```

## Development
```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest --cov
```
## Licence
See [LICENSE](LICENSE)

## Security
See [SECURITY.md](SECURITY.md)

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md)

## Support
Open an [issue](/../../issues)
