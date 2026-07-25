<div align="center">
<img src="docs/assets/logo.png" align="center" width="144px" height="144px"/>

### Finances Tracker

_A small Flask application for tracking monthly finances. Built with SQLite and uv, and designed for local or containerised runs._

</div>

<div align="center">

[![Docker](https://img.shields.io/github/v/tag/sudo-kraken/finances-tracker?label=&logo=docker&style=for-the-badge&logoColor=white&color=blue)](https://github.com/sudo-kraken/finances-tracker/pkgs/container/finances-tracker) [![Helm](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fsudo-kraken%2Fhelm-charts%2Frefs%2Fheads%2Fmain%2Fcharts%2Ffinances-tracker%2FChart.yaml&query=%24.version&label=&logo=helm&style=for-the-badge&logoColor=0F1487&color=white)](https://github.com/sudo-kraken/helm-charts/tree/main/charts/finances-tracker) [![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fsudo-kraken%2Ffinances-tracker%2Fmain%2Fpyproject.toml&logo=python&logoColor=yellow&color=3776AB&style=for-the-badge)](https://github.com/sudo-kraken/finances-tracker/blob/main/pyproject.toml)
</div>

<div align="center">

[![OpenSSF Scorecard](https://img.shields.io/ossf-scorecard/github.com/sudo-kraken/finances-tracker?label=openssf%20scorecard&style=for-the-badge)](https://scorecard.dev/viewer/?uri=github.com/sudo-kraken/finances-tracker)

</div>

## Demo
<div align="center">
  
![Demo](docs/assets/preview.gif)  
*Animation shows the basic functionality of the application*
</div>

## Contents

- [Overview](#overview)
- [Architecture at a glance](#architecture-at-a-glance)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Docker](#docker)
- [Configuration](#configuration)
- [Database upgrades](#database-upgrades)
- [Health](#health)
- [Production notes](#production-notes)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Licence](#licence)
- [Security](#security)
- [Contributing](#contributing)
- [Support](#support)

## Overview

Create an account, sign in, and manage accounts, bills and incomes within monthly workspaces. The app uses Decimal handling for money values and provides a `/health` endpoint for orchestration.

## Architecture at a glance

- Flask app factory with `app:app` WSGI target
- SQLAlchemy for persistence
- Flask-Login for session management
- Health endpoint `GET /health`

## Features

- Per-user financial workspaces protected by Flask-Login
- Monthly workspaces with accounts, bills and incomes
- Accurate Decimal handling for money values
- Persistent SQLite storage with automatic schema upgrades
- `/health` endpoint for liveness checks
- Reproducible local development with uv
- Prebuilt container image on GHCR

## Prerequisites

- [Docker](https://www.docker.com/) / [Kubernetes](https://kubernetes.io/)
- (Alternatively) [uv](https://docs.astral.sh/uv/) and Python 3.13 for local development

## Quick start

Local development with uv

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
uv sync --all-extras
uv run flask --app app:app run --host 0.0.0.0 --port ${PORT:-7070}
```

## Docker

Pull and run

```bash
docker pull ghcr.io/sudo-kraken/finances-tracker:latest
docker run --rm -p 7070:7070 \
  -e PORT=7070 \
  -e SECRET_KEY="replace-with-a-long-random-value" \
  -v finances-data:/app/app/db \
  ghcr.io/sudo-kraken/finances-tracker:latest
```

The supplied rootless Podman Quadlet requires a private environment file instead
of embedding a secret in the unit. Create it before starting the unit:

```bash
install -d -m 0700 "$HOME/.config/containers/systemd"
printf 'SECRET_KEY=%s\n' "$(openssl rand -hex 32)" \
  > "$HOME/.config/containers/systemd/financestracker.env"
chmod 0600 "$HOME/.config/containers/systemd/financestracker.env"
```

Keep this file stable across restarts; changing the key invalidates existing
login sessions. A missing or empty key prevents the application from starting.

## Kubernetes (Helm)

You can deploy the app on Kubernetes using the published Helm chart:

```bash
helm install finances-tracker oci://ghcr.io/sudo-kraken/helm-charts/finances-tracker \
  --namespace finances-tracker --create-namespace
```

By default, the chart generates its own development `SECRET_KEY` and creates a PersistentVolumeClaim for the SQLite database.  
For production use, override values such as `secret.create=false` and provide your own secret.

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| PORT | no | 7070 | Port to bind |
| WEB_CONCURRENCY | no | 2 | Gunicorn worker processes |
| SECRET_KEY | yes |  | Long random key used to protect sessions and CSRF tokens |
| DATABASE_FOLDER | no | app/db | Folder for the bundled SQLite database |
| SQLALCHEMY_DATABASE_URI | no | sqlite:///\<DATABASE_FOLDER\>/finances.db | Advanced database URI override; the packaged app includes only the SQLite driver |
| FINANCES_TESTING | no | 0 | Enables test configuration |
| ALLOW_REGISTRATION | no | false | Allow additional users after the first account is created |
| SESSION_COOKIE_SECURE | no | false | Only send session cookies over HTTPS |

`.env` example

```dotenv
PORT=7070
WEB_CONCURRENCY=2
SECRET_KEY=replace-with-a-long-random-value
DATABASE_FOLDER=/app/app/db
SQLALCHEMY_DATABASE_URI=sqlite:////app/app/db/finances.db
ALLOW_REGISTRATION=false
SESSION_COOKIE_SECURE=true
```

On an empty installation, the registration page remains available until the
first account is created. Further registration is disabled unless
`ALLOW_REGISTRATION=true`.

## Database upgrades

Schema upgrades run automatically during application startup. Existing
databases are upgraded in place and their rows are preserved; no manual
migration command is required. Back up the database volume before deploying a
new application version as part of normal operational practice.

When ownership is added to an older database, existing financial data is
assigned to its first user. If the database contains financial data but no user,
the data is held by an unloginable migration account and transferred to the
first subsequently registered user.

## Health

- `GET /health` returns `{ "status": "healthy" }` when the database connection succeeds.
- A database failure returns HTTP 503 with `{ "status": "unhealthy" }`; internal error details are logged rather than exposed.

## Data and backups

- For SQLite, mount a volume to persist `app/db/finances.db` when using Docker.
- The packaged application and container support SQLite. A custom external
  database URI requires installing its Python driver in a custom build.

## Production notes

- Always set `SECRET_KEY` to a long random value and keep it stable between restarts.
- If you expose the app on the internet, put it behind a reverse proxy that terminates TLS and sets secure cookies.
- Set `SESSION_COOKIE_SECURE=true` whenever the app is served exclusively over HTTPS.

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
