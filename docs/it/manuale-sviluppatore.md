# Stoic ELN — Manuale dello sviluppatore

Questo manuale è per chi modifica il codice di Stoic. Copre
architettura, modelli, blueprint, layer di servizio, frontend,
internazionalizzazione, testing, e contribuzione.

---

## Stack

- **Python 3.12+** con type hints (`from __future__ import annotations`)
- **Flask 3.x** come framework web
- **SQLAlchemy 2.x** ORM con `Mapped[...]` style
- **SQLite** come storage (con **SQLCipher** opzionale per
  cifratura at-rest)
- **Jinja2** per i template + **HTMX** per interattività senza
  full page reload
- **Bootstrap 5.3** + **lucide-icons** per la UI
- **Flask-Babel** per internazionalizzazione (IT source language,
  EN target)
- **WTForms** + **Flask-WTF** per le form
- **Flask-Login** per sessioni utente
- **RDKit** per chimica (parsing SMILES, rendering molecole)
- **ReportLab** per PDF (etichette, schede, audit log)
- **cryptography** + **sqlcipher3-wheels** per cifratura
- **APScheduler** per backup notturni
- **pytest** per testing

---

## Layout repository

```
stoic-eln/
├── stoic_eln/
│   ├── __init__.py          # create_app factory + boot hooks
│   ├── config.py            # Config classes (Dev/Prod/Testing)
│   ├── extensions.py        # db, login_manager, babel, csrf
│   ├── models/              # SQLAlchemy models
│   │   ├── user.py
│   │   ├── substance.py
│   │   ├── inventory_item.py
│   │   ├── reaction.py + reaction_component.py + reaction_step.py
│   │   ├── run.py + run_component.py + run_step.py + ...
│   │   ├── mixture.py + mixture_prep.py + ...
│   │   ├── attachment.py
│   │   ├── settings.py      # AppSetting (key-value store)
│   │   ├── audit_log.py
│   │   ├── order.py
│   │   └── ...
│   ├── blueprints/          # Route handlers per modulo
│   │   ├── auth/
│   │   ├── main/
│   │   ├── substances/
│   │   ├── inventory/
│   │   ├── reactions/
│   │   ├── runs/
│   │   ├── mixtures/
│   │   ├── preps/
│   │   ├── orders/
│   │   ├── attachments/
│   │   ├── settings/
│   │   └── stats/
│   ├── services/            # Business logic, no Flask deps
│   │   ├── stoich.py        # Calcoli stechiometrici
│   │   ├── run_calc.py      # Math di run/component
│   │   ├── step_calc.py     # Math di run/step
│   │   ├── backup.py        # Backup automation + restore
│   │   ├── backup_crypto.py # AES-256-GCM envelope
│   │   ├── db_crypto.py     # SQLCipher integration
│   │   ├── passphrase_store.py  # Modi passphrase (none/prompt/file/env)
│   │   ├── attachments.py   # Upload, dedup, validation
│   │   ├── labels.py        # PDF labels (Avery + thermal)
│   │   ├── pdf_run.py       # PDF report di un run
│   │   ├── pdf_audit.py     # PDF audit log
│   │   ├── scheme_image.py  # Reaction scheme SVG
│   │   ├── pubchem.py       # Import sostanze da PubChem
│   │   ├── audit.py         # log_event helper
│   │   └── ...
│   ├── templates/           # Jinja2 templates
│   ├── static/              # CSS, JS, SVG icons GHS, fonts
│   └── translations/        # IT (source) + EN (.po + .mo)
├── tests/                   # pytest test suite
├── scripts/                 # CLI utilities + migrations
│   ├── init_db.py
│   ├── migrate_weekN.py
│   ├── heal_it_translations.py
│   ├── heal_en_translations.py
│   └── ...
├── docs/                    # Manuali utente/admin/sviluppatore
├── instance/                # DB + backups + attachments (non in repo)
│   ├── stoic_eln.db
│   ├── backups/
│   ├── attachments/
│   ├── auth_source          # Marker per passphrase source
│   └── backup.key           # Solo se modo=file
├── babel.cfg                # Configurazione pybabel extract
├── pyproject.toml           # Dipendenze + entry points
└── Makefile                 # `make run`, `make test`, `make i18n`
```

---

## Modelli principali

### Substance

Una specie chimica del catalogo. Identificata da InChIKey
(deduplica). Campi: nome, IUPAC, CAS, SMILES, InChI, formula,
MW, densità, stato fisico, GHS pittogrammi, frasi H/P, soglia
minima.

### InventoryItem (lotto)

Un'istanza fisica di una sostanza: codice batch, quantità
iniziale/residua (in g e mL — l'unità "primaria" dipende dallo
stato fisico), data acquisto, scadenza, fornitore, costo. FK a
Substance. Una sostanza → molti lotti.

### Reaction (template)

Una "ricetta" generica. Status `draft` → `published`. Solo
published possono diventare run. Campi: codice, titolo, SMILES
di reazione, descrizione, procedura (testo libero o step
strutturati), workup, checklist.

### ReactionComponent / ReactionStep

Componenti = sostanze con ruolo (SM/reagente/prodotto/solvente/
catalizzatore/altro), coefficiente stechiometrico (eq), quantità
fissa (g/mL/free). Step = passi della procedura con tempo,
temperatura, descrizione.

### Run

Una specifica esecuzione di una Reaction. Stati: `draft` →
`in_progress` → `completed`. Campi: codice batch generato, scala
target, lotti scelti per ogni componente, pesi reali, resa, note,
allegati. Una volta `completed`, immutabile.

### RunComponent / RunStep

Componenti del run con lotto bound + peso reale. Step con
checklist spuntabile.

### Mixture

Una preparazione fisica: nome, tipo (soluzione/eluente/tampone/
miscela reagenti/altro), concentrazione principale, solvente
principale, componenti strutturati opzionali (substance + role +
concentration), GHS override.

### MixturePrep

Evento di preparazione di una miscela. Codice batch, mixture FK,
target quantity, lotti precursori consumati, lotto prodotto.
Una mixture → molte prep. Una prep → un nuovo InventoryItem
della mixture.

### Attachment

File generico polimorfico via `(entity_type, entity_id)`.
Entity types: `run`, `reaction`, `substance`, `inventory_item`,
`mixture`, `mixture_prep`. Storage filesystem in
`instance/attachments/`, dedup SHA-256.

### AppSetting

Key-value store per configurazione globale: `currency.code`,
`backup.path`, `backup.hour`, `auth.passphrase_source`, ecc.
Usato per impostazioni che cambiano dinamicamente. Tutto tipato a
stringa, JSON encoding per dict/list.

### AuditLog

Append-only. Campi: timestamp, user_id, action, entity_type,
entity_id, details (JSON).

### User

Autenticazione tramite Flask-Login. Campi: username, full_name,
operator_code, password_hash (bcrypt), role (user/supervisor/
admin), is_active, locale, theme.

---

## Architettura

### Application factory

`stoic_eln.create_app(config_class, instance_path=None)`. Factory
pattern: ogni chiamata produce un Flask app fresco. Sequenza al
boot:

1. `Flask(__name__, instance_path=...)` — instance path overridable
   per test isolation
2. `config_class.init_app(app)`
3. `_configure_logging`
4. `_register_extensions` — SQLAlchemy, Babel, Login, CSRF,
   eventualmente SQLCipher integration via `_maybe_enable_sqlcipher`
5. `_register_blueprints`
6. `_register_template_context` — funzioni e variabili globali nei
   template
7. `_register_error_handlers`
8. `_register_cli` — comandi `flask init-db`, `flask backup`,
   `flask db-encrypt`, ecc.
9. `_ensure_schema(app)` — `db.create_all()` idempotente
10. Scheduler startup (skippato in TESTING)

### Boot path con DB cifrato

Se il DB live è cifrato (SQLCipher), `_maybe_enable_sqlcipher`:

1. Chiama `passphrase_store.ensure_default_source_setting`
   (legge/crea il marker `instance/auth_source`)
2. Detecta cifratura del DB tramite sniff dei primi 16 byte
   (un SQLite plain inizia con `"SQLite format 3\x00"`)
3. Se cifrato, ottiene la passphrase dal source configurato
4. Installa un `creator` function nel SQLAlchemy engine che
   apre connessioni con `PRAGMA key=...`

Il push dell'app_context attorno a `get_passphrase` è cruciale:
`passphrase_store.current_source()` legge `current_app.instance_path`
quando il fallback dal marker file è attivo.

### Blueprint pattern

Ogni feature è un blueprint indipendente: `stoic_eln/blueprints/foo/`
con `__init__.py` (definisce `bp`), `routes.py` (handlers),
opzionalmente `forms.py` (WTForms).

Convenzioni:

- Endpoint: `bp.route("/path", methods=["GET", "POST"])`
- Decorator: `@login_required` quasi sempre
- HTMX detection: `if request.headers.get("HX-Request"):` →
  ritorna partial; else → render template completo o redirect
- Per le mutazioni in-place (toggle, edit inline), pattern
  HTMX OOB swap

### Service layer

I service in `stoic_eln/services/` contengono business logic
**senza Flask dependencies dirette** dove possibile. Esempi:

- `stoich.py`: dato un componente con eq e una scala di riferimento,
  calcola g/mL/mmol. Pure functions.
- `run_calc.py`, `step_calc.py`: idem per i calcoli specifici di
  componenti di run e step.
- `backup.py`: orchestrazione backup (create, list, restore).
  Dipende da Flask per `current_app.instance_path` + AppSetting.
- `backup_crypto.py`: cifratura/decifratura AES-256-GCM. Funzioni
  pure (passphrase + bytes → bytes).
- `db_crypto.py`: idem per SQLCipher. `is_encrypted_db`,
  `encrypt_db`, `decrypt_db`, `make_sqlcipher_creator`.
- `passphrase_store.py`: gestione modi passphrase. Cache di
  processo. Stateful ma con `reset_cache()` per testing.

### Frontend

UI server-rendered con Jinja2 + HTMX per interattività mirata:

- Modifiche inline di campi (edit-in-place tramite HTMX swap)
- Form submission senza ricaricare la pagina (HTMX + partial response)
- Upload di file con feedback live
- Toggle di checklist con OOB swap

Niente SPA, niente bundling JS pesante. Solo `htmx.org` (CDN-loaded)
+ `lucide-icons` (CDN) + un po' di vanilla JS per dettagli specifici
(es. molecule drawer, SmilesDrawer).

CSS: Bootstrap 5.3 + custom in `static/css/stoic.css`. Tema
chiaro/scuro tramite `data-bs-theme` sull'`<html>`.

Component pattern: template parziali in `templates/[modulo]/_foo.html`
inclusi via `{% include %}` o come response HTMX.

---

## Internazionalizzazione

Stoic è bilingue **IT (source) + EN**. Workflow:

```bash
# 1. Estrai stringhe dal codice → .pot
pybabel extract -F babel.cfg -o messages.pot .

# 2. Update i .po di ogni lingua
pybabel update -i messages.pot -d stoic_eln/translations

# 3. Heal: riempi automaticamente
python scripts/heal_it_translations.py    # IT: msgstr := msgid
python scripts/heal_en_translations.py    # EN: applica EN_FIXES dict

# 4. Compila .mo per il runtime
pybabel compile -d stoic_eln/translations
```

### Convenzioni di marking

Templates Jinja2:

```jinja2
{{ _("Salva") }}                  {# semplice #}
{{ _("Lotto %(n)s creato", n=code) }}   {# con sostituzione #}
{{ ngettext("%(n)d lotto", "%(n)d lotti", count, n=count) }}  {# plurali #}
```

Form classes (WTForms):

```python
from flask_babel import lazy_gettext as _l

class FooForm(FlaskForm):
    name = StringField(_l("Nome"), ...)
```

`lazy_gettext` è necessario perché le form vengono importate al
boot, prima che ci sia un request context.

Route handlers:

```python
from flask_babel import gettext as _

flash(_("Operazione completata."), "success")
```

### `EN_FIXES` dict

`scripts/heal_en_translations.py` contiene il dict
`EN_FIXES: dict[str, str]` con traduzioni manuali IT → EN.
Quando aggiungi una stringa nuova nel codice italiano:

1. Lancia `pybabel extract` + `pybabel update`
2. Lo script `heal_en_translations.py` segnala `Still empty
   (not in EN_FIXES): N` con la lista
3. Aggiungi le traduzioni a `EN_FIXES`
4. Rilancia lo script + `pybabel compile`

Mai modificare i `.po` a mano per nuove traduzioni: gli script
sono la source of truth. I `.po` sono solo output.

---

## Testing

`pytest` con coverage. ~400 test. `make test` o:

```bash
.venv/bin/pytest tests/ -v
```

Suite veloce (~2 min) perché:
- Test usano SQLite `:memory:` di default (TestingConfig)
- Fixture `app` da `conftest.py` ricrea schema fresh per test
- Niente fixture cross-test, isolamento totale

### Fixture chiave (`tests/conftest.py`)

- `app`: factory che crea un Flask app con `TestingConfig` e
  `instance_path` isolato (`tmp_path_factory.mktemp`)
- `client`: test client HTTP
- `admin_user`: utente admin precreato

Fixture autouse:

- `_scrub_real_instance_dir` (session): pulisce `instance/auth_source`
  e `instance/backup.key` reali a inizio sessione (sicurezza
  vs precedenti run con codice vecchio)
- `_reset_passphrase_cache` (function): wipea la cache module-level
  di `passphrase_store` prima/dopo ogni test
- `_no_env_passphrase` (function): rimuove `STOIC_BACKUP_PASSPHRASE`
  dall'env per evitare leak dalla shell del developer

### Test isolation per `instance_path`

`create_app(TestingConfig, instance_path=tmp_path)` è il pattern
canonico. Mai sovrascrivere `app.instance_path` dopo `create_app`:
i boot hooks (es. `_maybe_enable_sqlcipher`) leggono il path
durante `create_app` stesso.

### Opt-in SQLCipher in test

Di default i test skippano l'hook `_maybe_enable_sqlcipher`
(`if app.config.get("TESTING")`). Per test che esercitano
specificamente la cifratura del DB live:

```python
class _Cfg(TestingConfig):
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    SQLCIPHER_TEST_ENABLE = True  # opt-in
```

---

## Migrazioni DB

Stoic ha un approccio idempotente: `db.create_all()` al boot
crea tabelle/colonne mancanti senza toccare i dati esistenti.

Per **migrazioni di dati** (es. backfilling di colonne nuove,
restructuring di valori esistenti), script una-tantum in
`scripts/migrate_*.py`. Pattern:

```python
"""Migrate week N patch M — short description."""
from stoic_eln import create_app
from stoic_eln.extensions import db
from stoic_eln.models import ...

app = create_app()
with app.app_context():
    # Esegui le tue query SQLAlchemy / SQL grezzo
    # Stampa cosa hai fatto
    db.session.commit()
```

Lo si lancia: `.venv/bin/python scripts/migrate_weekN.py`. Gli
script di migrazione sono **idempotenti per design** — possono
essere rilanciati senza danno.

Le PATCH-NOTES di ogni patch indicano esplicitamente se serve
una migrazione manuale e quale script eseguire.

---

## CLI

Stoic registra comandi Flask custom in `_register_cli`. Quelli
principali:

```bash
flask init-db                  # Crea schema
flask create-user [--admin]    # Crea utente interattivo
flask backup                   # Backup manuale
flask backups-list             # Lista backup esistenti
flask db-status                # Stato cifratura DB live
flask db-encrypt --yes         # Cifra DB live
flask db-decrypt --yes         # Decifra DB live
flask passphrase-test          # Verifica config passphrase
flask scheduler-status         # Stato scheduler backup
```

I comandi vivono come `@app.cli.command("nome")` in `__init__.py`.

---

## Aggiungere una nuova feature

Workflow tipico:

1. **Modello**: aggiungi tabella in `models/foo.py`. Usa
   `Mapped[...]` style. Import in `models/__init__.py` se vuoi
   esporlo come `from stoic_eln.models import Foo`.
2. **Schema**: `db.create_all()` al prossimo boot lo crea
   automaticamente. Per modifiche a tabelle esistenti (nuove
   colonne), serve uno script di migrazione.
3. **Blueprint**: `stoic_eln/blueprints/foo/__init__.py` (definisci
   `bp = Blueprint("foo", __name__, url_prefix="/foo")`),
   `routes.py` (handler), opzionalmente `forms.py` (WTForms).
4. **Templates**: `stoic_eln/templates/foo/list.html`,
   `detail.html`, `form.html`. Estendi `base.html`.
5. **Service** (se logic complessa): `stoic_eln/services/foo.py`
   con funzioni pure. I blueprint chiamano il service, non
   l'inverso.
6. **Test**: `tests/test_foo.py`. Almeno: smoke test per le route
   GET, test per le mutation, edge case.
7. **i18n**: tutte le stringhe user-visible wrappate in `_(...)`
   o `_l(...)`. Lancia `pybabel extract && update && heal_en && compile`.
8. **Audit**: invoca `log_event(action=..., entity_type=...,
   entity_id=...)` dopo ogni mutation significativa.

---

## Sicurezza

### CSRF

Flask-WTF aggiunge token CSRF automatici a tutte le form. I
template usano `{{ csrf_token() }}` per HTMX/JS submissions.

### SQL injection

SQLAlchemy ORM parametrizza tutto. Mai costruire query con
string formatting. L'eccezione: `PRAGMA key='...'` per SQLCipher
non accetta parametri — usa `safe.replace("'", "''")` per
escape SQL standard.

### XSS

Jinja2 autoescape è on. Per inserire HTML grezzo (es. il filter
markdown), usare `|safe` esplicito su contenuto trusted.

### File upload

`services/attachments.py` valida:

- Denylist estensioni: `exe`, `html`, `js`, `svg` (XSS risk),
  `py`, ecc. Sempre rifiutati.
- Allowlist estensioni: PDF, immagini, dati lab. Solo quelli.
- Size limit: 100 MB per file (configurabile).
- Filename sanitization: `secure_filename()` di werkzeug.
- SHA-256 storage filename: `{sha256[:16]}_{safe_name}`.

### Path traversal

Mai concatenare path con input utente senza `secure_filename`.
Per leggere file da disco, usa `send_from_directory(safe_root,
filename)` di Flask.

### Authentication

Bcrypt password hash via passlib. Cookie sessions firmati. CSRF
sempre attivo. Login required quasi ovunque (whitelist esplicito
per `/auth/login`, `/static/...`, ecc.).

### Encryption

Vedi sezione "Crittografia e backup" del manuale admin. Tutte le
operazioni sicure usano `cryptography` o `sqlcipher3` — nessuna
crittografia custom roll-your-own.

---

## Contribuzione

### Stile codice

- Type hints obbligatori per signature pubbliche
- `from __future__ import annotations` in cima ai file Python
- Docstring chiare (in inglese, anche se la UI è IT)
- Niente line > 88 caratteri salvo eccezioni motivate
- Black + isort sono OK; non ci sono pre-commit hook
- Mai f-string in `_()` (Babel non estrae): usa `%`-format

### Convention commit

`Settimana N, patch M[.k] — short description`. Esempi:

- `Settimana 6, patch 14.3 — Passphrase source selectable + prompt mode`
- `Settimana 6, patch 14.4 — Allegati su mixture/mixture_prep`

### Test prima del merge

```bash
make test
# o
.venv/bin/pytest tests/ -q
```

Target: zero regressioni. I 6 legacy `test_reactions.py::test_*`
falliscono dalla 13.5 — è uno stato noto, non bloccante.

### Patch tarball workflow

Per consegne incrementali:

1. Implementa le modifiche
2. `make test` per zero regressioni
3. `git diff --stat` per la lista dei file modificati
4. Stage in `/tmp/patch-stage/stoic-eln/` con la stessa struttura
5. Aggiungi `PATCH-NOTES.md` (lista modifiche + applicazione +
   eventuali migrazioni)
6. `tar -czf stoic-eln-week6-patch-N.tar.gz stoic-eln/`

Il destinatario applica con `tar -xzvf ... -C ~/Projects/`.
