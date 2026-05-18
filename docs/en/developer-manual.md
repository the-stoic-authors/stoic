# Stoic ELN — Developer manual

This manual is for those modifying Stoic's code. Covers
architecture, models, blueprints, service layer, frontend,
internationalisation, testing, and contribution.

---

## Stack

- **Python 3.12+** with type hints (`from __future__ import annotations`)
- **Flask 3.x** as web framework
- **SQLAlchemy 2.x** ORM with `Mapped[...]` style
- **SQLite** as storage (with optional **SQLCipher** for
  at-rest encryption)
- **Jinja2** for templates + **HTMX** for interactivity without
  full page reload
- **Bootstrap 5.3** + **lucide-icons** for UI
- **Flask-Babel** for i18n (IT source language, EN target)
- **WTForms** + **Flask-WTF** for forms
- **Flask-Login** for user sessions
- **RDKit** for chemistry (SMILES parsing, molecule rendering)
- **ReportLab** for PDFs (labels, sheets, audit log)
- **cryptography** + **sqlcipher3-wheels** for encryption
- **APScheduler** for nightly backups
- **pytest** for testing

---

## Repository layout

```
stoic-eln/
├── stoic_eln/
│   ├── __init__.py          # create_app factory + boot hooks
│   ├── config.py            # Config classes (Dev/Prod/Testing)
│   ├── extensions.py        # db, login_manager, babel, csrf
│   ├── models/              # SQLAlchemy models
│   ├── blueprints/          # Route handlers per module
│   ├── services/            # Business logic, minimal Flask deps
│   ├── templates/           # Jinja2 templates
│   ├── static/              # CSS, JS, SVG GHS icons, fonts
│   └── translations/        # IT (source) + EN (.po + .mo)
├── tests/                   # pytest test suite
├── scripts/                 # CLI utilities + migrations
├── docs/                    # User/admin/developer manuals
├── instance/                # DB + backups + attachments (not in repo)
│   ├── stoic_eln.db
│   ├── backups/
│   ├── attachments/
│   ├── auth_source          # Marker for passphrase source
│   └── backup.key           # Only if mode=file
├── babel.cfg                # pybabel extract config
├── pyproject.toml           # Dependencies + entry points
└── Makefile                 # `make run`, `make test`, `make i18n`
```

---

## Main models

### Substance

A chemical species from the catalog. Identified by InChIKey
(deduplication). Fields: name, IUPAC, CAS, SMILES, InChI,
formula, MW, density, physical state, GHS pictograms, H/P
phrases, minimum threshold.

### InventoryItem (batch)

A physical instance of a substance: batch code, initial/remaining
quantity (in g and mL — the "primary" unit depends on physical
state), purchase date, expiry, supplier, cost. FK to Substance.
One substance → many batches.

### Reaction (template)

A generic "recipe". Status `draft` → `published`. Only published
ones can become runs. Fields: code, title, reaction SMILES,
description, procedure (free text or structured steps), workup,
checklist.

### ReactionComponent / ReactionStep

Components = substances with role (SM/reagent/product/solvent/
catalyst/other), stoichiometric coefficient (eq), fixed quantity
(g/mL/free). Steps = procedure steps with time, temperature,
description.

### Run

A specific execution of a Reaction. States: `draft` →
`in_progress` → `completed`. Fields: generated batch code, target
scale, batches chosen for each component, real weights, yield,
notes, attachments. Once `completed`, immutable.

### RunComponent / RunStep

Run components with bound batch + real weight. Steps with
tickable checklist.

### Mixture

A physical preparation: name, type (solution/eluent/buffer/
reagent mix/other), primary concentration, primary solvent,
optional structured components (substance + role +
concentration), GHS override.

### MixturePrep

A mixture preparation event. Batch code, mixture FK, target
quantity, consumed precursor batches, produced batch. One
mixture → many preps. One prep → one new InventoryItem of the
mixture.

### Attachment

Generic polymorphic file via `(entity_type, entity_id)`. Entity
types: `run`, `reaction`, `substance`, `inventory_item`,
`mixture`, `mixture_prep`. Filesystem storage in
`instance/attachments/`, SHA-256 dedup.

### AppSetting

Key-value store for global configuration: `currency.code`,
`backup.path`, `backup.hour`, `auth.passphrase_source`, etc.
Used for settings that change dynamically. All string-typed,
JSON encoding for dict/list.

### AuditLog

Append-only. Fields: timestamp, user_id, action, entity_type,
entity_id, details (JSON).

### User

Authentication via Flask-Login. Fields: username, full_name,
operator_code, password_hash (bcrypt), role (user/supervisor/
admin), is_active, locale, theme.

---

## Architecture

### Application factory

`stoic_eln.create_app(config_class, instance_path=None)`. Factory
pattern: each call produces a fresh Flask app. Boot sequence:

1. `Flask(__name__, instance_path=...)` — instance path
   overridable for test isolation
2. `config_class.init_app(app)`
3. `_configure_logging`
4. `_register_extensions` — SQLAlchemy, Babel, Login, CSRF,
   possibly SQLCipher integration via `_maybe_enable_sqlcipher`
5. `_register_blueprints`
6. `_register_template_context` — global functions and
   variables in templates
7. `_register_error_handlers`
8. `_register_cli` — commands `flask init-db`, `flask backup`,
   `flask db-encrypt`, etc.
9. `_ensure_schema(app)` — idempotent `db.create_all()`
10. Scheduler startup (skipped in TESTING)

### Boot path with encrypted DB

If the live DB is encrypted (SQLCipher), `_maybe_enable_sqlcipher`:

1. Calls `passphrase_store.ensure_default_source_setting`
   (reads/creates the `instance/auth_source` marker)
2. Detects DB encryption via first-16-byte sniff (a plain
   SQLite starts with `"SQLite format 3\x00"`)
3. If encrypted, obtains the passphrase from the configured
   source
4. Installs a `creator` function in the SQLAlchemy engine that
   opens connections with `PRAGMA key=...`

The app_context push around `get_passphrase` is crucial:
`passphrase_store.current_source()` reads
`current_app.instance_path` when the marker-file fallback is
active.

### Blueprint pattern

Each feature is an independent blueprint:
`stoic_eln/blueprints/foo/` with `__init__.py` (defines `bp`),
`routes.py` (handlers), optionally `forms.py` (WTForms).

Conventions:

- Endpoint: `bp.route("/path", methods=["GET", "POST"])`
- Decorator: `@login_required` almost always
- HTMX detection: `if request.headers.get("HX-Request"):` →
  returns partial; else → renders full template or redirects
- For in-place mutations (toggle, inline edit), HTMX OOB swap
  pattern

### Service layer

Services in `stoic_eln/services/` contain business logic
**without direct Flask dependencies** where possible. Examples:

- `stoich.py`: given a component with eq and a reference scale,
  computes g/mL/mmol. Pure functions.
- `run_calc.py`, `step_calc.py`: same for run-component and
  run-step specific calculations.
- `backup.py`: backup orchestration (create, list, restore).
  Depends on Flask for `current_app.instance_path` +
  AppSetting.
- `backup_crypto.py`: AES-256-GCM encrypt/decrypt. Pure
  functions (passphrase + bytes → bytes).
- `db_crypto.py`: same for SQLCipher. `is_encrypted_db`,
  `encrypt_db`, `decrypt_db`, `make_sqlcipher_creator`.
- `passphrase_store.py`: passphrase mode management. Process
  cache. Stateful but with `reset_cache()` for testing.

### Frontend

Server-rendered UI with Jinja2 + HTMX for targeted interactivity:

- Inline field edits (edit-in-place via HTMX swap)
- Form submission without page reload (HTMX + partial response)
- File upload with live feedback
- Checklist toggle with OOB swap

No SPA, no heavy JS bundling. Just `htmx.org` (CDN-loaded) +
`lucide-icons` (CDN) + a bit of vanilla JS for specific details
(e.g. molecule drawer, SmilesDrawer).

CSS: Bootstrap 5.3 + custom in `static/css/stoic.css`. Light/
dark theme via `data-bs-theme` on `<html>`.

Component pattern: partial templates in
`templates/[module]/_foo.html` included via `{% include %}` or
as HTMX response.

---

## Internationalisation

Stoic is bilingual **IT (source) + EN**. Workflow:

```bash
# 1. Extract strings from code → .pot
pybabel extract -F babel.cfg -o messages.pot .

# 2. Update each language's .po
pybabel update -i messages.pot -d stoic_eln/translations

# 3. Heal: auto-fill
python scripts/heal_it_translations.py    # IT: msgstr := msgid
python scripts/heal_en_translations.py    # EN: apply EN_FIXES dict

# 4. Compile .mo for runtime
pybabel compile -d stoic_eln/translations
```

### Marking conventions

Jinja2 templates:

```jinja2
{{ _("Save") }}                  {# simple #}
{{ _("Batch %(n)s created", n=code) }}   {# with substitution #}
{{ ngettext("%(n)d batch", "%(n)d batches", count, n=count) }}  {# plurals #}
```

Form classes (WTForms):

```python
from flask_babel import lazy_gettext as _l

class FooForm(FlaskForm):
    name = StringField(_l("Name"), ...)
```

`lazy_gettext` is necessary because forms are imported at boot,
before there's a request context.

Route handlers:

```python
from flask_babel import gettext as _

flash(_("Operation completed."), "success")
```

### `EN_FIXES` dict

`scripts/heal_en_translations.py` contains the
`EN_FIXES: dict[str, str]` dict with manual IT → EN translations.
When you add a new Italian string in code:

1. Run `pybabel extract` + `pybabel update`
2. The `heal_en_translations.py` script reports `Still empty
   (not in EN_FIXES): N` with the list
3. Add translations to `EN_FIXES`
4. Re-run the script + `pybabel compile`

Never modify `.po` files by hand for new translations: the
scripts are the source of truth. The `.po` files are just
output.

---

## Testing

`pytest` with coverage. ~400 tests. `make test` or:

```bash
.venv/bin/pytest tests/ -v
```

Fast suite (~2 min) because:
- Tests use SQLite `:memory:` by default (TestingConfig)
- The `app` fixture from `conftest.py` recreates schema fresh
  per test
- No cross-test fixtures, total isolation

### Key fixtures (`tests/conftest.py`)

- `app`: factory that creates a Flask app with `TestingConfig`
  and isolated `instance_path` (`tmp_path_factory.mktemp`)
- `client`: HTTP test client
- `admin_user`: precreated admin user

Autouse fixtures:

- `_scrub_real_instance_dir` (session): cleans up real
  `instance/auth_source` and `instance/backup.key` at start of
  session (safety vs previous runs with old code)
- `_reset_passphrase_cache` (function): wipes the module-level
  cache of `passphrase_store` before/after each test
- `_no_env_passphrase` (function): removes
  `STOIC_BACKUP_PASSPHRASE` from env to avoid leaks from the
  developer's shell

### Test isolation for `instance_path`

`create_app(TestingConfig, instance_path=tmp_path)` is the
canonical pattern. Never override `app.instance_path` after
`create_app`: boot hooks (e.g. `_maybe_enable_sqlcipher`) read
the path during `create_app` itself.

### Opt-in SQLCipher in tests

By default tests skip the `_maybe_enable_sqlcipher` hook (`if
app.config.get("TESTING")`). For tests that specifically
exercise live DB encryption:

```python
class _Cfg(TestingConfig):
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    SQLCIPHER_TEST_ENABLE = True  # opt-in
```

---

## DB migrations

Stoic takes an idempotent approach: `db.create_all()` at boot
creates missing tables/columns without touching existing data.

For **data migrations** (e.g. backfilling new columns,
restructuring existing values), one-shot scripts in
`scripts/migrate_*.py`. Pattern:

```python
"""Migrate week N patch M — short description."""
from stoic_eln import create_app
from stoic_eln.extensions import db
from stoic_eln.models import ...

app = create_app()
with app.app_context():
    # Run your SQLAlchemy / raw SQL queries
    # Print what you did
    db.session.commit()
```

You run it: `.venv/bin/python scripts/migrate_weekN.py`. Migration
scripts are **idempotent by design** — they can be re-run without
harm.

The PATCH-NOTES of each patch explicitly indicate whether a
manual migration is needed and which script to run.

---

## CLI

Stoic registers custom Flask commands in `_register_cli`. The
main ones:

```bash
flask init-db                  # Create schema
flask create-user [--admin]    # Create user interactively
flask backup                   # Manual backup
flask backups-list             # List existing backups
flask db-status                # Live DB encryption status
flask db-encrypt --yes         # Encrypt live DB
flask db-decrypt --yes         # Decrypt live DB
flask passphrase-test          # Verify passphrase config
flask scheduler-status         # Backup scheduler status
```

The commands live as `@app.cli.command("name")` in `__init__.py`.

---

## Adding a new feature

Typical workflow:

1. **Model**: add a table in `models/foo.py`. Use `Mapped[...]`
   style. Import in `models/__init__.py` if you want to expose
   it as `from stoic_eln.models import Foo`.
2. **Schema**: `db.create_all()` at next boot creates it
   automatically. For modifications to existing tables (new
   columns), a migration script is needed.
3. **Blueprint**: `stoic_eln/blueprints/foo/__init__.py` (define
   `bp = Blueprint("foo", __name__, url_prefix="/foo")`),
   `routes.py` (handler), optionally `forms.py` (WTForms).
4. **Templates**: `stoic_eln/templates/foo/list.html`,
   `detail.html`, `form.html`. Extend `base.html`.
5. **Service** (if complex logic):
   `stoic_eln/services/foo.py` with pure functions. Blueprints
   call the service, not the reverse.
6. **Tests**: `tests/test_foo.py`. At minimum: smoke test for
   GET routes, tests for mutations, edge cases.
7. **i18n**: wrap all user-visible strings in `_(...)` or
   `_l(...)`. Run `pybabel extract && update && heal_en &&
   compile`.
8. **Audit**: invoke `log_event(action=..., entity_type=...,
   entity_id=...)` after every significant mutation.

---

## Security

### CSRF

Flask-WTF automatically adds CSRF tokens to all forms. Templates
use `{{ csrf_token() }}` for HTMX/JS submissions.

### SQL injection

SQLAlchemy ORM parametrises everything. Never build queries with
string formatting. The exception: `PRAGMA key='...'` for
SQLCipher doesn't accept parameters — use `safe.replace("'",
"''")` for standard SQL escape.

### XSS

Jinja2 autoescape is on. To insert raw HTML (e.g. the markdown
filter), use explicit `|safe` on trusted content.

### File upload

`services/attachments.py` validates:

- Extension denylist: `exe`, `html`, `js`, `svg` (XSS risk),
  `py`, etc. Always rejected.
- Extension allowlist: PDF, images, lab data. Only those.
- Size limit: 100 MB per file (configurable).
- Filename sanitisation: werkzeug's `secure_filename()`.
- SHA-256 storage filename: `{sha256[:16]}_{safe_name}`.

### Path traversal

Never concatenate paths with user input without
`secure_filename`. To read files from disk, use Flask's
`send_from_directory(safe_root, filename)`.

### Authentication

Bcrypt password hash via passlib. Signed cookie sessions. CSRF
always active. Login required almost everywhere (explicit
whitelist for `/auth/login`, `/static/...`, etc.).

### Encryption

See "Encryption and backups" section of the admin manual. All
secure operations use `cryptography` or `sqlcipher3` — no custom
roll-your-own crypto.

---

## Contributing

### Code style

- Mandatory type hints for public signatures
- `from __future__ import annotations` at the top of Python
  files
- Clear docstrings (in English, even though the UI is IT)
- No lines > 88 chars unless well motivated
- Black + isort are OK; no pre-commit hooks
- Never f-strings in `_()` (Babel doesn't extract): use `%`-format

### Commit convention

`Week N, patch M[.k] — short description`. Examples:

- `Week 6, patch 14.3 — Passphrase source selectable + prompt mode`
- `Week 6, patch 14.4 — Attachments on mixture/mixture_prep`

### Test before merge

```bash
make test
# or
.venv/bin/pytest tests/ -q
```

Target: zero regressions. The 6 legacy `test_reactions.py::test_*`
fail since 13.5 — known state, not blocking.

### Patch tarball workflow

For incremental deliveries:

1. Implement changes
2. `make test` for zero regressions
3. `git diff --stat` for the list of modified files
4. Stage in `/tmp/patch-stage/stoic-eln/` with same structure
5. Add `PATCH-NOTES.md` (changes list + application + possible
   migrations)
6. `tar -czf stoic-eln-week6-patch-N.tar.gz stoic-eln/`

The recipient applies with `tar -xzvf ... -C ~/Projects/`.
