<div align="center">
<img src="docs/assets/logo.png" align="center" width="144px" height="144px"/>

### Finances Tracker

_A small Flask application for tracking monthly finances. SQLite is used by default and it can be switched to any SQLAlchemy supported database. Built with uv and designed for local or containerised runs._

</div>

<div align="center">

[![Docker](https://img.shields.io/github/v/tag/sudo-kraken/finances-tracker?label=docker&logo=docker&style=for-the-badge)](https://github.com/sudo-kraken/finances-tracker/pkgs/container/finances-tracker) [![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fsudo-kraken%2Ffinances-tracker%2Fmain%2Fpyproject.toml&logo=python&logoColor=yellow&color=3776AB&style=for-the-badge)](https://github.com/sudo-kraken/finances-tracker/blob/main/pyproject.toml)
</div>

<div align="center">

[![OpenSSF Scorecard](https://img.shields.io/ossf-scorecard/github.com/sudo-kraken/finances-tracker?label=openssf%20scorecard&style=for-the-badge)](https://scorecard.dev/viewer/?uri=github.com/sudo-kraken/finances-tracker)

</div>

## Demo
<div align="center">
  
![Demo](docs/assets/preview.gif)  
*Animation shows the basic functionality of the application*
</div>

## Overview

Create an account, sign in, and manage accounts, bills and incomes within monthly workspaces. The app uses Decimal handling for money values and provides a `/health` endpoint for orchestration.

## Architecture at a glance

- Flask app factory with `app:app` WSGI target
- SQLAlchemy for persistence
- Flask-Login for session management
- Health endpoint `GET /health`

## Features

- User sign in via Flask-Login
- Monthly workspaces with accounts, bills and incomes
- Accurate Decimal handling for money values
- SQLite by default with SQLAlchemy URI override
- `/health` endpoint for liveness checks
- Reproducible local development with uv
- Prebuilt container image on GHCR

## Prerequisites

- [Docker](https://www.docker.com/) / [Kubernetes](https://kubernetes.io/)
- (Alternatively) [uv](https://docs.astral.sh/uv/) and Python 3.13 for local development

## Quick start

Local development with uv

```bash
uv sync --all-extras
uv run flask --app app:app run --host 0.0.0.0 --port ${PORT:-7070}
```

## Docker

Pull and run

```bash
docker pull ghcr.io/sudo-kraken/finances-tracker:latest
docker run --rm -p 7070:7070 \
  -e PORT=7070 \
  ghcr.io/sudo-kraken/finances-tracker:latest
```

## Kubernetes (Helm)

You can deploy the app on Kubernetes using the published Helm chart:

```bash
helm install finances-tracker oci://ghcr.io/sudo-kraken/helm-charts/finances-tracker \
  --namespace finances-tracker --create-namespace
```

By default, the chart generates its own development `SECRET_KEY` and creates a PersistentVolumeClaim for the SQLite database.  
For production use, override values such as `secret.create=false` and provide your own secret, or switch to an external database via `SQLALCHEMY_DATABASE_URI`.

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| PORT | no | 7070 | Port to bind |
| WEB_CONCURRENCY | no | 2 | Gunicorn worker processes |
| SECRET_KEY | yes in production |  | Flask secret key used for sessions |
| SQLALCHEMY_DATABASE_URI | no | sqlite:///app/db/finances.db | Database URI |
| FINANCES_TESTING | no | 0 | Enables test configuration |

`.env` example

```dotenv
PORT=7070
WEB_CONCURRENCY=2
SECRET_KEY=change-me
SQLALCHEMY_DATABASE_URI=sqlite:///app/db/finances.db
```

## Health

- `GET /health` returns `{ "ok": true }`

## Data and backups

- For SQLite, mount a volume to persist `app/db/finances.db` when using Docker.
- For other databases, use their native backup tooling.

## Production notes

- Always set `SECRET_KEY` in production.
- If you expose the app on the internet, put it behind a reverse proxy that terminates TLS and sets secure cookies.

## Development

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest --cov
```

## Troubleshooting

- If the app fails to start with a database error, verify `SQLALCHEMY_DATABASE_URI` and that the target directory exists for SQLite.
- If log output is noisy, adjust the logging level via your process manager or container runtime.

## Licence
See [LICENSE](LICENSE)

## Security
See [SECURITY.md](SECURITY.md)

## Contributing
Feel free to open issues or submit pull requests if you have suggestions or improvements.
See [CONTRIBUTING.md](CONTRIBUTING.md)

## Support
Open an [issue](/../../issues)
