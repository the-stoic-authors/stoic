# Stoic ELN — Patch A: Production WSGI (gunicorn + scheduler fix)

Prima delle quattro patch che portano Stoic da "Quick start sul Mac"
a "Self-hosted lab server" (level 2 verso la v1.0). Posa le
fondamenta di production deployment.

## Cosa risolve

Stoic ha un **scheduler in-process** (APScheduler) che esegue il
backup notturno alle 03:00 UTC. È inizializzato dentro `create_app()`,
quindi attualmente parte ogni volta che l'app viene creata.

Questo va bene per `flask run` (un processo, uno scheduler). Sotto
gunicorn con `--workers N`, però, **ogni worker importa wsgi.py,
chiama create_app, e fa partire il suo scheduler** → N backup
notturni alle 03:00. Conseguenze possibili: backup corrotti per
race condition, log di sistema sporcati, rotazione errata della
retention.

Questa patch sposta lo scheduler nel processo **master di gunicorn**,
dove esiste esattamente una volta. I worker non lo toccano più.

## Architettura

### `create_app(start_scheduler=True)`

Nuovo parametro keyword-only.

  - `True` (default) preserva il comportamento esistente: `flask run`,
    script, test continuano a funzionare uguali (i test già skippavano
    tramite il check `TESTING` interno a `init_scheduler`).
  - `False` salta l'init scheduler. Usato da `wsgi.py`.

### `wsgi.py` (nuovo)

Entrypoint pulito per gunicorn / uWSGI / mod_wsgi:

```python
from stoic_eln import create_app
app = create_app(start_scheduler=False)
```

`start_scheduler=False` perché in multi-worker il scheduler vive
nel master, non nei worker.

### `gunicorn.conf.py` (nuovo)

Config file che gunicorn carica con `-c`. Espone via env var:

  - `STOIC_BIND` (default `127.0.0.1:5001`) — **loopback di default**
    per non esporre Stoic in LAN senza un'esplicita scelta
    dell'operatore
  - `STOIC_WORKERS` (default `2`) — sensato per Pi 4 / piccoli server
  - `STOIC_TIMEOUT` (default `120s`) — il PDF puó essere lento
  - `STOIC_LOGLEVEL` (default `info`)

Hook `when_ready`: chiamato una sola volta dal master DOPO che i
worker sono stati forkati. Crea un'app col `start_scheduler=True`
e la mantiene viva via reference modulare globale. Il
`BackgroundScheduler` (APScheduler) parte come thread nel master;
i thread non vengono ereditati da `fork()`, quindi lo scheduler
esiste **esattamente una volta**, nel master.

### `LinuxSystemdPlatform.install_daemon` aggiornato

`stoic install --daemon` su Linux ora genera un unit che usa
gunicorn:

```
ExecStart={venv}/gunicorn -c gunicorn.conf.py wsgi:app
```

Più: il messaggio post-install spiega esplicitamente che Stoic è
bound su `127.0.0.1` e indica le due opzioni per esporre in LAN
(Caddy reverse proxy raccomandato, oppure cambio diretto di
`STOIC_BIND` a `0.0.0.0`).

## File creati

  - **`wsgi.py`** (radice del repo) — entrypoint WSGI
  - **`gunicorn.conf.py`** (radice del repo) — config gunicorn
  - **`tests/test_production_wsgi.py`** (7 test):
    - `create_app()` default chiama `init_scheduler`
    - `create_app(start_scheduler=False)` NON chiama `init_scheduler`
    - `wsgi.app` importabile, è un'app Flask
    - import di `wsgi` non avvia scheduler
    - `gunicorn.conf.py` è importabile + espone `bind`, `workers`,
      `timeout`, `when_ready`
    - Env vars `STOIC_BIND`, `STOIC_WORKERS`, `STOIC_TIMEOUT` passano
      attraverso correttamente
    - Default `STOIC_BIND` è loopback (sicurezza)

## File modificati

  - **`stoic_eln/__init__.py`** — `create_app` ha nuovo kw arg
    `start_scheduler: bool = True`
  - **`stoic_eln/cli/platform.py`** — `LinuxSystemdPlatform.install_daemon`
    usa gunicorn invece di flask run, bind 127.0.0.1, messaggio
    aggiornato
  - **`pyproject.toml`** — aggiunta `gunicorn>=21.2,<24.0` alle
    dipendenze principali
  - **`docs/en/admin-manual.md`** e **`docs/it/manuale-amministratore.md`**
    — sezione Deployment riallineata col nuovo entrypoint, esempio
    `/etc/systemd/system/stoic.service` aggiornato, env vars
    documentate

### Nessun cambio a:

  - Tests esistenti (594 → 601 attesi, tutti i precedenti devono
    restare verdi)
  - Backup / encryption (già implementato, fuori scope)
  - CLI dei comandi `stoic backup`, `stoic db-encrypt` (invariati)
  - `flask run` per dev (continua a funzionare uguale)

## Validazione sandbox

  - ✅ 7/7 nuovi test verdi
  - ✅ Nessuna regression nella suite (557 passed nel sandbox,
    594 sul Mac atteso → 601)
  - ✅ Smoke test reale: `gunicorn -c gunicorn.conf.py wsgi:app`
    parte, scheduler-master ready, worker booted, login page
    HTTP 200, static asset HTTP 200, graceful shutdown su SIGTERM
  - ✅ ruff format + check clean

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-production-wsgi-patch.tar.gz -C ~/Projects/

# Installa gunicorn (nuova dep)
.venv/bin/pip install -e .

# Run test
make test 2>&1 | tail -3
```

Atteso: **601 passed** (594 + 7).

## Verifica manuale (opzionale, su Mac)

Per provare gunicorn anche sul Mac in modalità "production-like":

```
cd ~/Projects/stoic-eln
.venv/bin/pip install -e .
SECRET_KEY=dev FLASK_ENV=production \
DATABASE_URL=sqlite:///instance/stoic_eln.db \
STOIC_BIND=127.0.0.1:5001 STOIC_WORKERS=2 \
.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
```

Dovresti vedere:
- "Stoic: starting background scheduler in master"
- 2 worker partiti
- App raggiungibile su http://127.0.0.1:5001

## Cosa NON è in questa patch

Tre patch successive completano il setup production:

  - **Patch B**: Docker + Caddy reverse proxy + HTTPS self-signed
  - **Patch C**: `install-linux.sh` (orchestratore "da Ubuntu fresco
    a Stoic running")
  - **Patch D**: deployment reale su `stoichub` (validazione live)

Patch A è self-contained e mergiabile da sola. Le successive
costruiscono su di lei.
