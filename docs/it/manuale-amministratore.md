# Stoic ELN — Manuale dell'amministratore

Questo manuale copre installazione, configurazione, gestione utenti,
sicurezza dei dati, backup, audit, e deployment di Stoic. È destinato
a chi ha responsabilità di sistema. Per il workflow di laboratorio
vedi il manuale utente; per modificare il codice vedi il manuale
dello sviluppatore.

---

## Installazione

### Prerequisiti

- Python 3.12 o superiore
- ~500 MB di disco per il software + ~10–50 MB per il DB iniziale
- Un Mac, Linux x86_64, o Raspberry Pi. Il **3B con 1 GB di RAM**
  è il minimo verificato sul campo (vedi *Produzione su Raspberry
  Pi*); un 4 o 5 ha ovviamente più margine

### Setup ambiente di sviluppo (Mac/Linux)

```bash
# Clona o estrai il sorgente in ~/Projects/stoic-eln
cd ~/Projects/stoic-eln

# Crea l'ambiente virtuale
python3.12 -m venv .venv
source .venv/bin/activate

# Installa Stoic + dipendenze
pip install -e .
```

Le dipendenze principali installate automaticamente:

- **Flask 3.x** + Flask-Babel + Flask-Login + Flask-WTF
- **SQLAlchemy 2.x** + sqlcipher3-wheels (per cifratura del DB live)
- **RDKit** (rendering molecole)
- **ReportLab** + svglib (generazione PDF: etichette, schede,
  audit log)
- **cryptography** (cifratura backup AES-256-GCM, Argon2id KDF)
- **APScheduler** (backup notturni)
- **PIL/Pillow** (manipolazione immagini)

### Configurazione iniziale

Apri `~/.zshrc` (o `~/.bashrc`) e aggiungi:

```bash
export FLASK_APP=stoic_eln
```

Poi inizializza il database e crea il primo amministratore:

```bash
flask init-db
flask create-user --admin
# Username: rico
# Full name: Rico Di Rosso
# Operator code: RDR
# Password: [scelta forte]
```

Avvia in modalità sviluppo:

```bash
flask run
```

Apri `http://localhost:5000` nel browser e fai login con
l'account appena creato.

---

## Gestione utenti

### Ruoli

Stoic ha tre ruoli, ordinati per privilegi crescenti:

| Ruolo | Cosa può fare |
|---|---|
| **Utente** | Esegue run, consuma lotti, carica allegati. Non modifica template di reazione o sostanze del catalogo. |
| **Supervisore** | Tutto di utente, più: crea/modifica reazioni e sostanze, gestisce miscele e fornitori. |
| **Amministratore** | Tutto di supervisore, più: gestisce utenti, configurazione globale, backup, audit log completo. |

### Creare un utente

Da CLI:

```bash
flask create-user
# Username: alice
# Full name: Alice Rossi
# Operator code: ALR
# Role: user / supervisor / admin
# Password: [...]
```

Da UI: **Settings → Utenti → Nuovo utente**. Compila i campi e
salva. Stoic non ha self-signup: gli utenti vengono sempre creati
da un admin. Comunica username e password al nuovo utente, che
cambierà la password al primo accesso da Profilo → Cambia password.

### Modificare un utente

**Settings → Utenti → [nome]**. Puoi modificare full name, operator
code, ruolo, locale di default (it/en), stato attivo/disattivo. Non
puoi modificare il tuo stesso ruolo (per sicurezza: serve un secondo
admin per fare il downgrade).

### Reset password

**Settings → Utenti → [nome] → Reset password**. Genera una nuova
password temporanea, comunica all'utente. Lo costringe a cambiarla
al prossimo login.

### Disattivare un utente

Stessa pagina, toggle "Attivo". Disattivare invece di eliminare:
gli utenti disattivi non possono fare login ma restano nei record
storici (run eseguiti, allegati caricati). Eliminare un utente
spezza i riferimenti.

---

## Crittografia e backup

Stoic offre tre livelli di protezione:

1. **Backup automatici** — non sono cifrati di default. Vivono in
   `instance/backups/`.
2. **Cifratura dei backup** (AES-256-GCM, Argon2id KDF) — quando
   abiliti la passphrase. Backup futuri salvati come
   `.db.gz.enc`.
3. **Cifratura del DB live** (SQLCipher 4, AES-256-CBC + HMAC-
   SHA512 a livello di pagina) — `stoic_eln.db` opaco senza
   passphrase.

I tre livelli sono indipendenti: puoi avere solo backup plain
(default), backup cifrati ma DB live plain, oppure entrambi
cifrati. **La passphrase è la stessa per entrambi** — un solo
segreto da ricordare.

### Sorgenti della passphrase

Da `Settings → Crittografia e backup → Sorgente passphrase`:

| Modo | Dove vive la passphrase | TTY al boot? | Threat model |
|---|---|---|---|
| `none` | da nessuna parte | no | Niente cifratura. Default fresh install. |
| `prompt` | solo in RAM | **sì** | Disco rubato = protetto. Max sicurezza. |
| `file` | `instance/backup.key` (0600) | no | Comoda per sviluppo. |
| `env` | `STOIC_BACKUP_PASSPHRASE` | no | Server con systemd-creds o Docker secrets. |

**Quale scegliere:**

- **Mac di sviluppo personale, FileVault attivo**: `file` o
  `prompt`. FileVault già protegge il disco a spento.
- **Mac/desktop senza disk encryption**: `prompt`. La passphrase
  non esiste sul disco; chi rubasse il filesystem trova solo dati
  cifrati senza chiave.
- **Server Linux con auto-restart**: `env` (via systemd
  EnvironmentFile o systemd-creds + TPM).
- **Raspberry Pi, o qualsiasi server di laboratorio non
  presidiato**: `file` se la macchina è fisicamente sicura, oppure
  `env` tramite l'ambiente del container. Anche `prompt` funziona,
  ma su una macchina senza monitor significa che dopo ogni riavvio
  il server resta giù finché qualcuno non entra via SSH a digitare
  la passphrase — vedi *Produzione su Raspberry Pi*.

### Attivare la cifratura del DB live

1. Configura una passphrase: scegli un modo (es. `prompt`),
   salva
2. Inserisci la passphrase
3. Ferma Stoic (`Ctrl-C` su `flask run`)
4. Esegui: `flask db-encrypt --yes` — fa prima un backup di
   sicurezza, poi cifra in place
5. Riavvia Stoic

Da qui in poi, il file `stoic_eln.db` è opaco. Aperto con qualsiasi
client SQLite mostra "file is not a database". Solo Stoic con
passphrase corretta può leggerlo.

### Decifrare il DB live (rollback)

```bash
flask db-decrypt --yes
```

Ferma Stoic prima. Crea un backup pre-decifratura, poi sovrascrive
con la versione plain. Riavvia Stoic normalmente.

### Status

```bash
flask db-status
# Output: "Live DB at instance/stoic_eln.db: encrypted (SQLCipher)"
# Oppure: "Live DB at instance/stoic_eln.db: plain SQLite"
```

### Backup manuale

```bash
flask backup
# Crea: instance/backups/stoic_eln-20260513-093000.db.gz[.enc]
```

In modo `prompt`, ti viene richiesta la passphrase. In modo `file`
o `env` è automatico.

### Configurazione scheduler automatico

`Settings → Crittografia e backup → Backup automatici`:

- **Ora (UTC)**: default 03:00
- **Minuto**: default 0
- **Conserva ultimi (giorni)**: default 30 (rolling daily backups)
- **+ uno a settimana per (settimane)**: default 12 (rolling
  weekly backups dopo i daily)

Stoic mantiene automaticamente la retention configurata. I backup
più vecchi vengono eliminati ogni notte. La cifratura (se attiva)
viene applicata a tutti i backup automatici.

### Ripristino

`Settings → Crittografia e backup → Backup esistenti → Ripristina`.

Stoic:
1. Crea un backup di sicurezza del DB attuale (`pre-restore`)
2. Sostituisce il DB con il contenuto del backup
3. Riavvia richiesto

Se il backup era cifrato e il sistema attuale è cifrato, il restore
re-cifra automaticamente con la passphrase attuale.

### Cambiare la passphrase

Importante: **cambiare la passphrase rende illeggibili tutti i
backup cifrati esistenti**. Fai questo solo se sei sicuro o se hai
deciso di accettarne la perdita.

1. Fai un backup di sicurezza con la passphrase attuale
2. `Settings → Crittografia e backup → Cambia passphrase`
3. Decifra il DB live (se cifrato) prima di cambiare
4. Cambia, ri-cifra

Lo script `flask db-decrypt && [change passphrase] && flask
db-encrypt` è il workflow sicuro.

### Cosa fare se perdi la passphrase

Sintomi: Stoic non parte ("Cannot decrypt"), oppure backup cifrati
non aprono.

- Se il DB live è ancora plain: solo i backup cifrati sono persi.
  Il sistema continua a funzionare normalmente. Considera di
  disattivare la cifratura temporaneamente (`Settings → ...` →
  scegli `none`).
- Se il DB live è cifrato e la passphrase è persa: i dati sono
  irrecuperabili. Devi ripartire da zero. Lezione cara: testa
  sempre la passphrase prima di cifrare il DB live.

---

## Configurazione globale

`Settings → Impostazioni generali`.

### Valuta

Codice ISO 4217 a 3 lettere (EUR, USD, JPY, ecc.). Stoic mostra
il simbolo riconosciuto (€, $, £, ¥) o il codice. Usata per
tutti i costi (lotti, ordini, run, statistiche).

### Template codice run

Formato generato per i codici batch dei prodotti dei run. Default:
`{reaction.code}-{year}-{seq:03d}` → `EST-MEOH-2026-001`.
Personalizzabile da `Settings → Codice run`.

### Template codice preparazione

Idem per le preparazioni di miscele. Default:
`{mixture.slug}-{year}-{seq:03d}` → `HCL1N-2026-001`.

### Lingua di default

Default per nuovi utenti. Ogni utente può cambiare la sua dal
profilo.

### Soglie globali

- **Default soglia minima**: quando crei una sostanza nuova senza
  specificare, questa è la soglia sotto la quale apparirà negli
  avvisi della dashboard.

---

## Audit log

`Settings → Audit log`. Tutte le azioni significative sono
registrate con:

- Timestamp UTC
- Utente
- Azione (`create`, `update`, `delete`, `login`, `logout`,
  `download_run_pdf`, `upload_attachment`, ecc.)
- Entità (tipo + ID)
- Dettagli (JSON con campi rilevanti)

Filtri disponibili: per utente, per azione, per entità, per
intervallo date. Esportabile come **CSV** o **PDF**.

L'audit log è append-only: nessuna route lo modifica. Solo gli
admin lo vedono completo. Gli utenti vedono i loro record da
`Profilo`.

---

## Deployment

### Sviluppo locale (Mac)

Quello descritto sopra. `flask run` su localhost:5000.

### Docker + Caddy (raccomandato per un server di laboratorio)

È la strada più breve per avere un server funzionante con HTTPS, ed
è quella che la maggior parte delle installazioni dovrebbe prendere.
La guida completa è **[Installare Stoic con
Docker](install-docker.md)**; dal punto di vista
dell'amministratore quello che conta è **dove vive lo stato**,
perché è ciò che si salva e ciò che non si deve buttare.

| Volume | Montato su | Contiene |
|---|---|---|
| `stoic-instance` | `/app/instance` | il database SQLite, `backups/`, `backup.key`, `auth_source` |
| `stoic-attachments` | `/app/data/attachments` | i file allegati ai run |
| `caddy-data`, `caddy-config` | quelli di Caddy | certificati TLS e CA locale |

`STOIC_INSTANCE_PATH=/app/instance` in `docker-compose.yml` è ciò
che tiene backup e file della passphrase sul primo volume. Non
toglierla: senza, Flask ricade su un percorso dentro il virtualenv
dell'immagine, che sta nel layer scrivibile del container e viene
distrutto dal successivo `docker compose up -d`. Le versioni
precedenti alla 1.5.6 avevano esattamente questo bug; vedi la nota
di aggiornamento nella guida Docker.

Due abitudini specifiche del container:

- `FLASK_APP` dentro l'immagine non è impostata di proposito,
  quindi ogni comando CLI di questo manuale diventa
  `docker compose exec stoic flask --app stoic_eln <comando>`.
- Dopo `docker compose up -d` su un'installazione nuova, lancia
  `init-db` prima di aprire il browser. Altrimenti l'utente
  amministratore non esiste.

### Produzione su Linux + systemd

Stoic include un entrypoint production-ready (`wsgi.py`) e una
configurazione gunicorn calibrata (`gunicorn.conf.py`). Gestiscono
correttamente un dettaglio sottile: lo scheduler interno dei backup
gira nel processo gunicorn **master**, non in ogni worker — così il
backup notturno scatta una volta sola anche con `--workers 4`.

Crea `/etc/systemd/system/stoic.service`:

```ini
[Unit]
Description=Stoic ELN
After=network.target

[Service]
Type=simple
User=stoic
WorkingDirectory=/opt/stoic-eln
EnvironmentFile=/etc/stoic/stoic.env
ExecStart=/opt/stoic-eln/.venv/bin/gunicorn -c /opt/stoic-eln/gunicorn.conf.py wsgi:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Il file `/etc/stoic/stoic.env`:

```
# Obbligatoria in produzione
SECRET_KEY=generare-con-python-secrets-token_hex-32

# Opzionale: solo se i backup cifrati sono abilitati
STOIC_BACKUP_PASSPHRASE=la-tua-passphrase-segreta

# Tuning gunicorn opzionale (default mostrati)
STOIC_BIND=127.0.0.1:5001
STOIC_WORKERS=2
STOIC_TIMEOUT=120
```

Permessi: `chmod 600 /etc/stoic/stoic.env`, `chown root:stoic
/etc/stoic/stoic.env` (leggibile solo da root e dal gruppo stoic).
Oppure usa `systemd-creds` + TPM per cifratura at-rest dei
secret.

**Esposizione in LAN**: il default `STOIC_BIND=127.0.0.1:5001`
significa che Stoic è raggiungibile solo dal server stesso. Per
renderlo disponibile sulla rete del laboratorio, due opzioni:

  - **Raccomandato**: metti Caddy (o nginx) davanti, in ascolto
    su 443/80 e proxy verso `127.0.0.1:5001`. È l'unico modo per
    avere HTTPS, ed è quello che fa lo script `install-linux.sh`.
  - **Veloce e sporco**: cambia `STOIC_BIND` a `0.0.0.0:5001`.
    Stoic sarà raggiungibile in HTTP sulla LAN. Evitalo su reti
    condivise o non fidate.

Abilita e avvia:

```bash
systemctl enable stoic
systemctl start stoic
systemctl status stoic
```

### Produzione su Raspberry Pi

Usa la strada Docker qui sopra. Un Raspberry Pi 3B — la macchina
più povera fra quelle che Stoic dichiara come casa naturale — è
stato sottoposto a tre settimane di prova di tenuta su Pi OS Lite
64-bit, e i numeri sono comodi, non al limite:

| | Misurato | Soglia |
|---|---|---|
| RAM libera con 2 worker | 466 MB (minimo su 18 giorni: 465 MB) | ≥ 200 MB |
| Residente del container applicativo | ~230 MiB | — |
| Pagina reazione con schema disegnato lato server | 210 ms | < 3 s |
| PDF di un run, a caldo | 0.9 s | < 20 s |
| Temperatura massima su 5217 campioni | 47.8 °C | < 75 °C |
| Riavvio fino a `healthy` | 75 s | < 120 s |

Quindi **lascia `STOIC_WORKERS` a 2 anche su un Pi 3B.** Le
versioni precedenti di questo manuale raccomandavano 1: la misura
non lo sostiene, e il secondo worker dimezza circa la latenza al
99° percentile sotto uso concorrente.

Tre impostazioni vanno applicate prima di misurare qualsiasi cosa
su un Pi, e nessuna delle tre Stoic può farla al posto tuo:

- `gpu_mem=16` in `/boot/firmware/config.txt` — su una macchina
  senza monitor il firmware riserva altrimenti 76 MB alla GPU.
  Valgono ~50 MB di RAM utilizzabile.
- `cgroup_enable=memory cgroup_memory=1` in coda a
  `/boot/firmware/cmdline.txt` — Pi OS ha il controller cgroup
  della memoria **disattivato**, il che fa rispondere `0B` a
  `docker stats` e nasconde l'unico numero che serve per
  dimensionare i worker. Quel file è **una riga sola senza newline
  finale**: si appende con
  `sudo sed -i '1s/$/ cgroup_enable=memory cgroup_memory=1/'`, mai
  con `echo >>`, e prima se ne fa una copia.
- Pi OS a 64 bit non è facoltativo: RDKit pubblica wheel solo per
  aarch64, e sulla build a 32 bit l'immagine prova a compilarlo dai
  sorgenti.

Non esiste ancora un'immagine arm64 pubblicata, quindi su un Pi si
builda in locale e si aggiorna con
`git pull && docker compose build && docker compose up -d`. Lì
**mai** `docker compose pull`: sostituirebbe la tua build arm64 con
quella amd64 e il container si fermerebbe con `exec format error`.

**Sul modo `prompt` per la passphrase**: funziona su un Pi come
altrove, ma vuol dire che dopo ogni riavvio — aggiornamento del
kernel, black-out, qualsiasi cosa — un umano deve digitarla via
SSH. Su un server di laboratorio non presidiato di solito è il
compromesso sbagliato: meglio il modo `file` con la chiave sul
volume instance, e il disco protetto per conto suo. In ogni caso
non usare `flask run` come servizio permanente: è il server di
sviluppo di Werkzeug, a processo singolo e non irrobustito per
l'esposizione, e scavalca la configurazione gunicorn che esegue il
backup notturno nel master.

### Network e firewall

Stoic non implementa rate limiting o protezioni anti-bruteforce
oltre il login. **Non esporlo direttamente su Internet.** Usalo
solo su rete locale del laboratorio, o dietro VPN.

Se ti serve accesso remoto: Tailscale o WireGuard funzionano bene.

---

## Risoluzione problemi

**Stoic non parte: "no such table".** Il DB non è inizializzato.
`flask init-db`.

**"file is not a database".** Il DB è cifrato ma manca la
passphrase. Verifica modo (`prompt`/`file`/`env`) e fornisci la
passphrase. Test: `flask passphrase-test`.

**"Cannot decrypt".** Passphrase sbagliata, o DB corrotto. Prova
con `flask db-status`. Se passphrase corretta ma errore, ripristina
da backup recente.

**Backup notturni non partono.** Verifica APScheduler:
`flask scheduler-status`. Lo scheduler vive nel processo Stoic;
se Stoic è giù, niente backup. Controlla il log di systemd:
`journalctl -u stoic -f`.

**Allegato non visibile dopo upload.** Verifica `ATTACHMENTS_DIR`
in `config.py` — deve essere scrivibile. Default
`instance/attachments/`.

**Migrazione database fallita.** Stoic ha `_ensure_schema` che
crea tabelle mancanti al boot (idempotente). Le migrazioni di
dati esistenti (es. nuove colonne) sono in `scripts/migrate_*.py`,
da lanciare a mano dopo upgrade: `python scripts/migrate_weekN.py`.

---

## Backup off-site

Il backup notturno locale ti protegge da corruzione DB, ma non da
incendio o furto del computer.

Prima però va detto che cos'**è** un backup: una copia compressa
del database SQLite, e nient'altro. Gli allegati stanno fuori —
sotto `data/attachments/`, o sul volume `stoic-attachments` con
Docker — e non sono inclusi. Un laboratorio che allega spettri e
foto ai run deve metterli nel piano off-site a parte, altrimenti il
ripristino torna con tutti i record e nessun file.

Configura una sincronizzazione periodica della cartella
`instance/backups/` verso storage esterno (con Docker è `backups/`
dentro il volume `stoic-instance`):

- Rclone verso S3/Backblaze B2/Google Drive
- Restic con repository remoto
- Borg con server di backup
- Time Machine (Mac) include `instance/backups/` automaticamente
  se la cartella padre è inclusa

I backup cifrati sono **sicuri da copiare in cloud non
trusted** — chi prende il file non può aprirlo senza passphrase.

---

## Aggiornamento

Da installazione sorgente:

```bash
cd ~/Projects/stoic-eln
git pull  # o tar -xzvf nuova-patch.tar.gz
.venv/bin/pip install -e .  # aggiorna se le deps sono cambiate
```

Con Docker su x86_64:

```bash
cd ~/stoic
docker compose pull && docker compose up -d
```

Con Docker su arm64 (Raspberry Pi) — si builda in locale, **mai
pull**:

```bash
cd ~/stoic
git pull && docker compose build && docker compose up -d
```

Le migrazioni di schema sono automatiche (idempotenti). Se una
patch include uno script `scripts/migrate_*.py`, le PATCH-NOTES
lo specificano e te lo dicono di lanciarlo manualmente.

Dopo aggiornamento, riavvia Stoic. Buona pratica: fai un backup
manuale prima (`flask backup`).
