# Installare Stoic con Docker

Questo è il modo raccomandato per far girare Stoic su un server
di laboratorio dedicato. L'immagine Docker include Stoic, gunicorn,
Caddy (come reverse proxy con HTTPS automatico), e tutte le
dipendenze di sistema — niente venv Python da mantenere, niente
web server separato da configurare, e gli aggiornamenti sono un
solo comando.

Deployment testati:

  - Linux x86_64 (Ubuntu 22.04+, Debian 12+)
  - macOS (Intel + Apple Silicon) tramite Docker Desktop
  - Windows 11 tramite Docker Desktop + WSL2
  - Raspberry Pi 4 + Pi OS 64-bit (immagine arm64 — vedi Patch E)

## Prerequisiti

Una macchina con:

  - Docker Engine 24+ e Docker Compose v2
  - 2 GB di spazio disco libero per l'immagine e i dati in crescita
  - Accesso di rete a GitHub (per scaricare l'immagine) e a
    Let's Encrypt (solo se esponi pubblicamente)

Per installare Docker su Ubuntu/Debian:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Esci e rientra perché il cambio di gruppo abbia effetto
```

## Avvio rapido

```bash
# 1. Scarica i manifest di deployment
mkdir stoic && cd stoic
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/Caddyfile -o Caddyfile
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/.env.example -o .env

# 2. Modifica .env — come minimo imposta SECRET_KEY e STOIC_DOMAIN
nano .env

# 3. Avvia
docker compose up -d

# 4. Aspetta ~15 secondi per il primo avvio, poi apri il browser
#    Con STOIC_DOMAIN=stoic.local → https://stoic.local
#    Con STOIC_DOMAIN=lab.example.com → https://lab.example.com
```

La prima richiesta fa partire Caddy per generare il certificato TLS:

  - **Dominio reale** → certificato Let's Encrypt, pronto in ~10s.
    Le richieste successive servono dalla cache.
  - **Dominio `*.local`** → Caddy genera un certificato self-signed
    tramite la sua CA interna. Il browser avviserà ("Non sicuro"
    o simile); vedi la sezione "Fidarsi della CA locale di Caddy"
    sotto.

## Configurazione

Tutto vive in `.env`. Le due impostazioni obbligatorie:

### `SECRET_KEY`

Una stringa casuale lunga usata per firmare i cookie di sessione.
Generala con:

```bash
openssl rand -hex 32
```

Non condividerla mai e non committarla mai. Cambiarla fa il logout
di tutti gli utenti esistenti.

### `STOIC_DOMAIN`

Determina l'URL su cui Stoic risponde e la strategia TLS:

| Valore | TLS | Quando usarlo |
|--------|-----|---------------|
| `stoic.local` (default) | Caddy self-signed | Install solo LAN, accessibile sulla rete locale |
| `lab.example.com` | Let's Encrypt | Deploy pubblico con un dominio reale |
| `localhost` | Solo HTTP | Sviluppo / testing |

Perché i domini `*.local` siano risolti sui dispositivi client,
serve una delle seguenti:

  - **mDNS / Bonjour**: funziona automaticamente su macOS, iOS, e
    su Linux con `avahi-daemon` installato
  - **Entry in `/etc/hosts`** su ogni client:
    ```
    192.168.1.42 stoic.local
    ```
  - **Un DNS server locale** (Pi-hole, il tuo router) che punta
    `stoic.local` all'IP LAN del server

### Impostazioni opzionali

| Variabile | Default | Note |
|-----------|---------|------|
| `STOIC_TLS_EMAIL` | (vuoto) | Usato per le notifiche Let's Encrypt |
| `STOIC_WORKERS` | `2` | Worker gunicorn. Usa `1` su Pi 3B |
| `STOIC_TIMEOUT` | `120` | Timeout per richiesta in secondi |
| `STOIC_IMAGE` | `ghcr.io/the-stoic-authors/stoic:latest` | Fissa una versione |
| `LAB_NAME` | `Mio Laboratorio` | Nome di default finché non parte il wizard |
| `DEFAULT_LOCALE` | `it` | Lingua UI di default (`it` o `en`) |
| `STOIC_BACKUP_PASSPHRASE` | (vuoto) | Abilita i backup notturni cifrati |

## Fidarsi della CA locale di Caddy

Se hai usato un dominio `*.local`, la prima volta che apri Stoic
il browser mostra un avviso. Due modi per rimuoverlo:

### Opzione A: installa la root CA di Caddy su ogni client

È l'approccio più pulito, "mai più avvisi".

```bash
# Sul server, trova la root CA
docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt

# Copia il certificato sul tuo client (Mac, iOS, Linux, Windows)
# e installalo come trusted a livello di sistema. Esempio macOS:
#   security add-trusted-cert -d -r trustRoot \
#     -k /Library/Keychains/System.keychain root.crt
```

Ogni client lo fa una volta sola.

### Opzione B: accetta l'avviso per browser

Per accesso occasionale, clicca "Avanzate" → "Procedi a stoic.local"
nella pagina di avviso del browser. I browser moderni ricordano
la scelta per profilo.

## Aggiornare

```bash
# Scarica la nuova versione dell'immagine
docker compose pull

# Riavvia con la nuova immagine (lo stato nei volume è preservato)
docker compose up -d
```

Per fissare una versione specifica (raccomandato in produzione):

```bash
# In .env
STOIC_IMAGE=ghcr.io/the-stoic-authors/stoic:v1.0.0
```

Poi `docker compose up -d`.

## Backup

Il container Stoic fa un backup notturno automatico alle 03:00 UTC
nel processo master. Il file cifrato finisce nel named volume
`stoic-backups`. Per estrarre un backup verso l'host:

```bash
docker compose exec stoic ls -la /app/var/backups
docker compose cp stoic:/app/var/backups/<nomefile> ./
```

Per abilitare la cifratura, imposta `STOIC_BACKUP_PASSPHRASE`
in `.env` (trattalo come il seed di un password manager —
perderlo rende i backup esistenti irrecuperabili).

## Fermare e rimuovere

```bash
# Ferma i container, mantieni i volume
docker compose down

# Ferma E cancella tutti i dati (DISTRUTTIVO)
docker compose down -v
```

## Risoluzione problemi

### `docker compose up` dice "address already in use"

Qualcosa sull'host (skype, un altro web server) sta usando la
porta 80 o 443. O fermi l'altro servizio, o cambi le porte
pubblicate in `docker-compose.yml`:

```yaml
caddy:
  ports:
    - "8443:443"
```

### Il browser mostra "ERR_CERT_AUTHORITY_INVALID"

Atteso alla prima visita se `STOIC_DOMAIN=stoic.local`. O fidi
la root CA di Caddy (sopra), o accetti l'avviso per browser.

### La pagina di login non carica mai, il container si riavvia

```bash
docker compose logs stoic
```

Causa più comune: `SECRET_KEY` mancante in `.env`.

### Non riesco a raggiungere `stoic.local` da un altro device

mDNS non funziona su quel device. O installa Bonjour /
avahi-daemon, o aggiungi una entry hosts che punta all'IP LAN
del server.
