# Stoic ELN

> **Lab notebook, refactored.**

An electronic lab notebook for organic chemists, designed for self-hosted lab deployment.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)

---

## Status

**v2.0.0a1 — Week 1 Foundation**

This is the foundation week of the v2 rewrite. What works:

- ✅ Application factory with dev/test/prod configs
- ✅ User model with Argon2 password hashing
- ✅ Audit log infrastructure
- ✅ Login / logout / change password
- ✅ Italian (default) + English translations
- ✅ Light / dark / system theme
- ✅ Layout with sidebar, header, theme + locale switchers
- ✅ Tests (pytest)

What's NOT here yet (coming in subsequent weeks):

- ⏳ Substances + PubChem (Week 2)
- ⏳ Inventory (Week 2)
- ⏳ Reaction templates (Week 3)
- ⏳ Run execution (Week 4)
- ⏳ Reports + admin + audit UI (Week 5)
- ⏳ Polish + RPi deploy + release (Week 6)

---

## Quick start (development)

### Prerequisites

- Python 3.11 or newer
- pip

### Setup

```bash
# 1. Clone or extract the project
cd stoic-eln/

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Configure environment
cp .env.example .env
# Edit .env if you want (defaults work for dev)

# 5. Initialize the database
python scripts/init_db.py
# This creates stoic_eln.db with an admin user (admin / admin123)

# 6. Run the app
flask --app stoic_eln run --debug
```

The app will be available at **http://localhost:5000**.

Login with **admin / admin123** (change this immediately via the "Change password" page).

---

## Running tests

```bash
pytest
```

For coverage:

```bash
pytest --cov=stoic_eln --cov-report=term-missing
```

---

## Project layout

```
stoic-eln/
├── stoic_eln/             # Application package
│   ├── __init__.py        # create_app() factory
│   ├── config.py          # Dev/test/prod configs
│   ├── extensions.py      # SQLAlchemy, Login, Babel, …
│   ├── models/            # SQLAlchemy models
│   ├── blueprints/        # Route handlers
│   ├── services/          # Business logic
│   ├── templates/         # Jinja2 templates
│   ├── static/            # CSS, JS, images
│   └── translations/      # Babel .po files (it, en)
├── scripts/               # Init DB, seeds, utilities
├── tests/                 # pytest suite
├── migrations/            # Alembic (added in Week 2)
├── pyproject.toml         # Dependencies + tool config
├── babel.cfg              # Translation extraction config
├── LICENSE                # GPL v3
└── README.md
```

---

## Development workflow

### Code style

This project uses **ruff** for linting and formatting (replaces black, isort, flake8).

```bash
ruff format .       # auto-format
ruff check . --fix  # lint + auto-fix
```

### Translations

Strings in Python use `_("...")` (or `lazy_gettext` for class-level strings).
Strings in templates use `{{ _("...") }}`.

To extract new strings to translate:

```bash
pybabel extract -F babel.cfg -o messages.pot stoic_eln/
pybabel update -i messages.pot -d stoic_eln/translations
# Edit stoic_eln/translations/en/LC_MESSAGES/messages.po
pybabel compile -d stoic_eln/translations
```

### Database migrations (added in Week 2)

```bash
flask --app stoic_eln db migrate -m "describe change"
flask --app stoic_eln db upgrade
```

---

## License

GPL v3 — see [LICENSE](LICENSE).

This means: you can use, modify, and redistribute Stoic ELN, but if you distribute
modifications you must also release them under GPL v3. This protects the open
ecosystem we are building.

---

## Acknowledgements

Stoic ELN uses these excellent open-source projects:

- [Flask](https://flask.palletsprojects.com/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [Bootstrap](https://getbootstrap.com/)
- [HTMX](https://htmx.org/) (added Week 2)
- [SmilesDrawer](https://github.com/reymond-group/smilesDrawer) (added Week 2)
- [Lucide icons](https://lucide.dev/)

Built by [Riccardo Di Rosso](https://github.com/) — and Claude.
