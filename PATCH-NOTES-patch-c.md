# Stoic ELN — Patch C: ProxyFix, /healthz, install-linux.sh, README

Terza della serie production. Chiude i finding della design review
post-B e completa l'esperienza "da Ubuntu fresco a Stoic running
con un comando". Dopo questa patch resta solo la validazione live
(Patch D su stoichub).

## 1. ProxyFix (bug fix reale)

`create_app` ora avvolge l'app in
`ProxyFix(x_for=1, x_proto=1, x_host=1)`. Senza, dietro Caddy:

  - `request.is_secure` era False → `url_for(_external=True)`
    generava URL `http://` (manifest PWA, redirect assoluti)
  - `request.remote_addr` era l'IP del container Caddy, non il
    client → audit log inquinati

Con header assenti (dev `flask run`) ProxyFix è un no-op — zero
impatto sullo sviluppo. `x_*=1` = fidati di esattamente un hop:
un client non può spoofare gli header attraverso un proxy
configurato correttamente (Caddy li sovrascrive).

## 2. `/healthz`

Endpoint di liveness dedicato: JSON `{"status": "ok"}`, niente
template, niente DB, niente auth. Dockerfile, compose e CI smoke
test ora puntano lì invece che su `/auth/login` (che renderizzava
un template completo ogni 30 secondi). Il CI mantiene comunque un
check su `/auth/login` + un asset statico dopo il readiness — è il
canarino per la classe di bug package-data.

## 3. install-linux.sh

Lo script "one command" promesso dal README:

```
curl -fsSL .../install-linux.sh | bash
```

Fa: installa Docker se manca (get.docker.com), scarica compose +
Caddyfile, genera SECRET_KEY casuale, chiede il dominio (legge da
/dev/tty quindi funziona anche sotto curl|bash), `docker compose
up -d`, stampa istruzioni finali con l'IP LAN per la config DNS.

Idempotente: non sovrascrive `.env` né i manifest esistenti.
Rifiuta di girare come root. Se installa Docker, si ferma e chiede
di rifare login (gruppo docker) — onesto invece che sudo-magico.

## 4. README ribaltato

La front door ora presenta Stoic come **self-hosted lab server**:
sezione "Architecture" nuova + Quick start server (one-liner) come
percorso primario; il setup venv/flask run è retrocesso a "Quick
start — development".

## 5. Doc CA per iOS/iPadOS

Sezione nuova in install-docker.md (EN+IT): come installare e
fidare la root CA di Caddy su iPad — incluso il passo
Impostazioni → Info → Impostazioni certificati che tutti
dimenticano e senza il quale la PWA non si installa pulita.
Necessaria per la Patch D (bench mode su iPad via stoichub).

## 6. ROADMAP.md

Checklist v1.0 verificabile (deployment / data safety / product /
hygiene) con il criterio di release esplicito: lista vuota → tag
v1.0.0 → prima immagine pubblicata. Mantenuta nello stesso commit
del lavoro che descrive.

## File

Nuovi: `scripts/installers/install-linux.sh`, `ROADMAP.md`,
`tests/test_patch_c_proxy_health.py` (8 test).
Modificati: `stoic_eln/__init__.py` (ProxyFix),
`stoic_eln/blueprints/main/routes.py` (/healthz), `Dockerfile`,
`docker-compose.yml`, `.github/workflows/docker-build.yml`
(healthcheck switch), `README.md`, `docs/{en,it}/install-docker.md`.

## Test (8 nuovi)

  - /healthz: 200 senza auth, JSON, no redirect
  - ProxyFix: X-Forwarded-For → remote_addr, X-Forwarded-Proto →
    is_secure=True, manifest OK sotto header proxy, no-op senza
    header
  - installer: esiste, eseguibile, struttura (no-root guard,
    SECRET_KEY da urandom, /dev/tty, compose up)
  - ROADMAP: esiste con checklist

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-patch-c-proxy-installer.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **629 passed** (621 + 8).

## Cosa NON c'è

  - Validazione live (Patch D — stoichub)
  - Publish su ghcr.io + multi-arch (Patch E)
  - Lo script installer è testato strutturalmente ma MAI eseguito
    su un Ubuntu reale: è esattamente quello che valideremo in D
