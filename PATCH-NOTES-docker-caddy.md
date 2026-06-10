# Stoic ELN — Patch B: Docker + Caddy

Seconda della serie production (post Patch A che ha introdotto
gunicorn + scheduler-in-master). Rende Stoic eseguibile come stack
Docker Compose con HTTPS automatico — `docker compose up -d` e
parti.

## Cosa risolve

Patch A ha reso Stoic production-grade ma richiedeva ancora a chi
installa di:
- Installare Python 3.12 + system deps a mano (Cairo, freetype,
  libsqlcipher se vuole encryption)
- Configurare systemd
- Mettere un reverse proxy davanti per HTTPS
- Generare certificati Let's Encrypt o self-signed manualmente

Patch B impacchetta tutto questo in uno stack standard
auto-contenuto. Il chimico-utente medio (con un Pi 4 e voglia di
provare Stoic) deve sapere solo: copia un docker-compose.yml,
edita .env, lancia `docker compose up -d`. Stop.

## Architettura

Due container nello stack:

  - **stoic** — l'app: gunicorn + APScheduler + Stoic stesso.
    NON pubblica porte sull'host. Vive solo nella rete docker
    interna. Healthcheck su `/auth/login`.
  - **caddy** — reverse proxy + TLS termination. Espone :80 e
    :443 sull'host. Risolve il servizio `stoic` via DNS docker
    interno.

Tre named volumes per persistenza:

  - `stoic-instance` (SQLite + chiavi + auth source)
  - `stoic-attachments` (file caricati dagli utenti)
  - `stoic-backups` (backup notturni)
  - `caddy-data` (certificati + ACME state)
  - `caddy-config` (config runtime Caddy)

### HTTPS via una variabile sola

`STOIC_DOMAIN` controlla la strategia TLS senza ulteriori toggle:

| Valore | TLS | Caso d'uso |
|--------|-----|------------|
| `stoic.local` (default) | Caddy internal CA self-signed | LAN-only |
| `lab.example.com` | Let's Encrypt automatico | Deployment pubblico |
| `localhost` | Solo HTTP | Dev / CI |

Caddy detecta il pattern da solo. Nessuna config aggiuntiva.

### Multi-stage Dockerfile

Stage 1 (builder, ~1.5 GB): Python 3.12, build tools, libcairo-dev,
compila tutto incluso `pybabel compile` per le translations.

Stage 2 (runtime, ~500 MB): Python 3.12 slim, solo i shared
library runtime, copy del venv preparato. Nessun build tool. tini
come PID 1 per la propagazione corretta dei signal.

Container gira come utente `stoic` non-root (UID 1000), security
hardening baseline.

### SQLCipher disabilitato in Docker

Il wheel `sqlcipher3-wheels` ha binari per linux x86_64 + macOS +
Windows ma NON per ARM Linux. Compilarlo dentro il Dockerfile
aggiungerebbe ~500MB di build-essential alla stage 1 senza beneficio
sostanziale: il **backup encryption** (AES-256-GCM con Argon2id)
esiste già a livello applicativo e è multipiattaforma.

Quindi: SQLCipher (DB live encrypted at rest) resta disponibile in
deployment nativo (es. via `pip install`) ma non in Docker. Backup
encryption è sempre disponibile.

Documentato esplicitamente nelle install-docker.md.

## File creati

  - **`Dockerfile`** — multi-stage build
  - **`.dockerignore`** — esclude .venv, instance, .env, ecc.
  - **`Caddyfile`** — reverse proxy + HTTPS automatico + security
    headers + gzip/zstd encoding
  - **`docker-compose.yml`** — orchestrazione due servizi + 5
    volumes + network bridge
  - **`.env.example`** — template ben commentato con SECRET_KEY
    blank, STOIC_DOMAIN default
  - **`.github/workflows/docker-build.yml`** — CI che builda
    l'immagine ad ogni push e fa smoke test (NO push automatico
    al registry — quello in Patch E)
  - **`docs/en/install-docker.md`** + **`docs/it/install-docker.md`**
    — guida completa: install Docker, configurazione, fidarsi della
    CA locale, upgrade, backup, troubleshooting
  - **`tests/test_docker_compose.py`** (20 test):
    - Dockerfile esiste, è multi-stage, runs as non-root, ha
      HEALTHCHECK, usa tini, entrypoint è gunicorn
    - compose ha esattamente 2 servizi, caddy pubblica 80+443,
      stoic NON pubblica porte, volumi persistenti definiti,
      depends_on con condition healthy
    - Caddyfile braces bilanciate, reverse_proxy a stoic:5001,
      usa $STOIC_DOMAIN, ha security headers
    - .env.example documenta le variabili richieste e ship con
      SECRET_KEY blank
    - .dockerignore esclude paths pericolosi e permette
      .env.example

## File modificati

Nessuno. Patch B è puramente additiva.

## Validazione sandbox

  - ✅ 20/20 nuovi test verdi al primo colpo
  - ✅ docker-compose.yml è YAML valido (struttura services / 
    volumes / networks ok)
  - ✅ Caddyfile braces bilanciate (14 open, 14 close)
  - ✅ Workflow GHA è YAML valido
  - ✅ Nessuna regression (577 passed nel sandbox, 601 sul Mac
    atteso → 621)
  - ✅ ruff format + check clean

**NON testato nel sandbox**: build effettiva dell'immagine
(`docker build`), avvio reale dello stack (`docker compose up`).
Questi richiedono il Docker daemon, sono validati dal workflow
GitHub Actions appena pushato.

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-docker-caddy-patch.tar.gz -C ~/Projects/

# Verifica unit test
make test 2>&1 | tail -3
```

Atteso: **621 passed** (601 + 20).

## Verifica manuale (raccomandata sul Mac)

Se hai Docker Desktop installato, prova lo stack localmente:

```
cd ~/Projects/stoic-eln
cp .env.example .env
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
# Imposta STOIC_DOMAIN=localhost in .env per HTTP semplice senza
# avvisi del browser (più facile per il primo test locale).

# Build + avvio
docker compose build
docker compose up -d

# Aspetta ~15 s, poi apri:
open http://localhost

# Vedi i log
docker compose logs -f

# Quando finisci di provare:
docker compose down  # mantiene i volumi
# o
docker compose down -v  # cancella TUTTO incluso DB
```

## Cosa NON è in questa patch

  - **`install-linux.sh`** (Patch C): script bash che orchestra
    Docker install + scarica i manifest + genera .env + lancia
    compose. Per ora l'utente fa i 3 `curl` a mano.
  - **CI publish su ghcr.io** (Patch E): la build c'è, ma non c'è
    il push automatico dell'immagine al registry. Quello arriva
    quando taggheremo v1.0.0.
  - **Build multi-arch** (Patch E): solo amd64 per ora. arm64 per
    Pi richiede setup buildx + cross-compile che vediamo separatamente.
  - **README ribaltato** (Patch C): la "front door" del repo ancora
    presenta Stoic come quick-start macOS. Cambierà quando lo
    script install-linux.sh sarà pronto e potremo dare l'esperienza
    completa "self-hosted server".
  - **Caddy serving static files**: il Caddyfile ha un blocco
    commentato per servire `/static/*` direttamente. Lo lasciamo
    disabilitato perché richiederebbe un volume mount aggiuntivo e
    per traffico basso (singolo lab) la differenza è invisibile.
    Abilitabile quando il carico lo giustifica.
  - **Validazione live su stoichub** (Patch D): tutto questo è da
    testare empiricamente su un Linux reale. Patch D è la sessione
    di deployment guidata.
