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
- Un Mac, Linux x86_64, o Raspberry Pi (4 o 5 raccomandato)

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
- **Raspberry Pi piccolo**: `prompt` con tmux per sessioni
  persistenti, oppure `file` se il Pi è in posto fisico sicuro.

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

### Produzione su Linux + systemd

Crea `/etc/systemd/system/stoic.service`:

```ini
[Unit]
Description=Stoic ELN
After=network.target

[Service]
Type=simple
User=stoic
WorkingDirectory=/opt/stoic-eln
EnvironmentFile=/etc/stoic/secret.env
ExecStart=/opt/stoic-eln/.venv/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --timeout 120 \
    "stoic_eln:create_app()"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Il file `/etc/stoic/secret.env`:

```
STOIC_BACKUP_PASSPHRASE=la-tua-passphrase-segreta
```

Permessi: `chmod 600 /etc/stoic/secret.env`, `chown root:stoic
/etc/stoic/secret.env` (leggibile solo da root e dal gruppo stoic).
Oppure usa `systemd-creds` + TPM per cifratura at-rest del
secret.

Abilita e avvia:

```bash
systemctl enable stoic
systemctl start stoic
systemctl status stoic
```

### Produzione su Raspberry Pi

Stessa configurazione systemd, ma con `--workers 1` (Pi ha meno
RAM) e magari `--bind 127.0.0.1:5000` + reverse proxy nginx
davanti se vuoi HTTPS.

Per il modo `prompt` su Pi (passphrase mai sul disco):

```bash
# SSH al Pi
ssh pi@stoic-server

# Tmux session persistente
tmux new -s stoic
cd /opt/stoic-eln
source .venv/bin/activate
flask run --host 0.0.0.0 --port 5000
# Inserisci passphrase quando chiede
# Ctrl-B D per detach (sessione resta in background)
# tmux attach -t stoic per riattaccarti
```

Svantaggio: se il Pi si riavvia (kernel update, blackout), serve
SSH manuale per ridigitare la passphrase. Compromise classico
sicurezza vs disponibilità.

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
incendio o furto del computer. Configura una sincronizzazione
periodica della cartella `instance/backups/` verso storage
esterno:

- Rclone verso S3/Backblaze B2/Google Drive
- Restic con repository remoto
- Borg con server di backup
- Time Machine (Mac) include `instance/backups/` automaticamente
  se la cartella padre è inclusa

I backup cifrati sono **sicuri da copiare in cloud non
trusted** — chi prende il file non può aprirlo senza passphrase.

---

## Aggiornamento

```bash
cd ~/Projects/stoic-eln
git pull  # o tar -xzvf nuova-patch.tar.gz
.venv/bin/pip install -e .  # aggiorna se le deps sono cambiate
```

Le migrazioni di schema sono automatiche (idempotenti). Se una
patch include uno script `scripts/migrate_*.py`, le PATCH-NOTES
lo specificano e te lo dicono di lanciarlo manualmente.

Dopo aggiornamento, riavvia Stoic. Buona pratica: fai un backup
manuale prima (`flask backup`).
