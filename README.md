# Finances Tracker

A small Flask application for tracking monthly finances. I originally built this for my own use, then decided to share it publicly regardless of it being a niche edge case for me, I wanted to fulfil requirements that other tools could not.

## Features

- Simple username and password sign in using Flask-Login
- SQLite by default via SQLAlchemy with an easy switch to any SQLAlchemy-supported database
- Monthly workspaces for budgeting
- Accounts within each month to organise bills and incomes
- Bills and incomes linked to accounts, with the option to link a bill to a specific income
- Mark bills as paid and track amounts with proper Decimal handling
- Position and size data for accounts persisted through a small JSON endpoint
- Clean app entry point so you can run it as `app:app` with Flask or Gunicorn
- Reproducible setup with uv, optional Docker image
- Test suite targeting 95 percent coverage across non-template code
- No external services required and no telemetry
- Configuration driven through environment variables for production

## Requirements

- Python 3.9 or newer
- uv for dependency management
- SQLite (bundled with Python’s sqlite3)

## Quick start

Install dependencies:

```sh
uv sync --dev
```

Run the development server with the public app object:

```sh
uv run flask --app app:app run --port 7070
```

Open http://localhost:7070

## Running with Gunicorn

```sh
uv run --no-dev gunicorn -w 2 -b 0.0.0.0:7070 app:app
```

## Configuration

All configuration lives in `app/config.py`. Important settings:

- `SECRET_KEY` must be set via environment in production:
  ```sh
  export SECRET_KEY='change-me'
  ```
- `SQLALCHEMY_DATABASE_URI` defaults to a SQLite file at `app/db/finances.db`.

For tests, the app switches to an in-memory SQLite database and disables CSRF if `FINANCES_TESTING=1` is present. The test suite sets this automatically.

## Tests and coverage

Run the suite:

```sh
uv run pytest --cov
```

Target coverage is 95 percent or higher across the `app/` package. The HTML views in `app/routes.py` are excluded from coverage so the focus is on models, forms, configuration and application wiring.

## Project layout

```
app/
  app.py            # builds and exports the Flask `app`
  config.py         # configuration
  extensions.py     # SQLAlchemy and LoginManager setup
  models.py         # database models
  routes.py         # blueprints and routes
  templates/        # Jinja templates
  static/           # CSS, JS, images
tests/
  conftest.py
  test_app_reload.py
  test_config.py
  test_forms.py
  test_models.py
  test_smoke.py
pyproject.toml      # project metadata and dependencies
uv.lock             # resolved lock file used in CI and Docker
```

## Docker

A minimal image using uv:

```sh
docker build -t finances-tracker .
docker run --rm -p 7070:7070 finances-tracker
```

The container listens on port 7070.

## Contributing

- Do not commit database files or secrets.
- Coding style is enforced with Ruff. Run:
  ```sh
  uv run ruff check --fix .
  uv run ruff format .
  ```
