# Stoic ELN — Setup guide (Mac)

Questa è la guida di avvio per il primo setup di Stoic ELN sul Mac.
Tutti i comandi vanno eseguiti in **Terminal**, dalla cartella del progetto.

---

## Pre-requisiti

Devono essere già installati:

- Python 3.11 o superiore (`python3 --version` deve dire 3.11.x, 3.12.x, o 3.13.x)
- git
- Una shell zsh (default su macOS)

Se hai dubbi su qualcuno di questi, fammelo sapere prima di continuare.

---

## Step 1 — Scompattare il progetto

Hai scaricato `stoic-eln-week1.tar.gz`. Scompattalo nella cartella scelta:

```bash
mkdir -p ~/Projects
cd ~/Projects
tar -xzf ~/Downloads/stoic-eln-week1.tar.gz
cd stoic-eln
ls
```

Dovresti vedere file come `pyproject.toml`, `README.md`, `Makefile`, e cartelle
`stoic_eln/`, `tests/`, `scripts/`.

---

## Step 2 — Creare l'ambiente virtuale

Un ambiente virtuale (venv) isola le dipendenze Python di Stoic ELN dal resto del
sistema. È una pratica standard Python e serve per non inquinare il Python globale.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Dopo l'attivazione, il prompt del terminale dovrebbe iniziare con `(.venv)`.
Esempio:

```
(.venv) riccardodirosso@MacBookPro stoic-eln %
```

**Importante:** ogni volta che apri un nuovo Terminal e vuoi lavorare su Stoic ELN,
devi rifare `source .venv/bin/activate` prima di tutti i comandi seguenti.

Per verificare che il venv usi Python 3.12:

```bash
python --version
```

Mi aspetto: `Python 3.12.x`.

---

## Step 3 — Installare le dipendenze

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

Il primo comando aggiorna pip al più recente. Il secondo installa Stoic ELN in
modalità "editable" (link simbolico al codice sorgente, così le modifiche al codice
sono immediate senza reinstallare) con tutte le dipendenze di sviluppo.

Dura 1-2 minuti. Alla fine vedrai una lista lunga di pacchetti installati.

---

## Step 4 — Configurare l'environment

```bash
cp .env.example .env
```

Per ora i default vanno bene. Se vuoi cambiare il nome del laboratorio
(che appare nell'header), apri `.env` con un editor e modifica `LAB_NAME`.

---

## Step 5 — Compilare le traduzioni

Le traduzioni in formato `.po` (testo) devono essere compilate in `.mo` (binario)
prima che Flask-Babel le possa usare.

```bash
pybabel compile -d stoic_eln/translations
```

Output atteso:

```
compiling catalog stoic_eln/translations/it/LC_MESSAGES/messages.po to stoic_eln/translations/it/LC_MESSAGES/messages.mo
compiling catalog stoic_eln/translations/en/LC_MESSAGES/messages.po to stoic_eln/translations/en/LC_MESSAGES/messages.mo
```

---

## Step 6 — Inizializzare il database

```bash
python scripts/init_db.py
```

Output atteso:

```
Creating tables...
✓ Admin user created: admin / admin123
  Change this password immediately after first login!

Done. Run the app with: flask --app stoic_eln run --debug
```

Nella cartella del progetto adesso troverai un file `stoic_eln.db` (è SQLite).
**Non aggiungerlo a git** — è già nel `.gitignore`.

---

## Step 7 — Avviare l'app

```bash
flask --app stoic_eln run --debug
```

Output atteso:

```
 * Serving Flask app 'stoic_eln'
 * Debug mode: on
 * Running on http://127.0.0.1:5000
```

Apri nel browser: **http://localhost:5000**

Dovresti vedere la pagina di login con:
- Logo Stoic ELN
- Tagline "Lab notebook, refactored."
- Campi username / password
- In alto a destra: switch tema (sole/luna/monitor) + switch lingua (IT/EN)

**Login con:**
- Username: `admin`
- Password: `admin123`

Dopo il login arrivi alla **Dashboard** con:
- Sidebar a sinistra con sezioni LABORATORIO, MAGAZZINO, ADMIN
- Voci di menu non ancora abilitate (sono per le settimane 2-5)
- 4 KPI card con valori vuoti (placeholder per le prossime settimane)

**Cose da provare:**
1. Click sull'icona luna (header in alto a destra) → tema scuro applicato istantaneamente
2. Click sul codice "IT"/"EN" → cambia lingua
3. Logout dal menu utente → torna alla pagina di login

---

## Step 8 — Cambiare la password admin (importante!)

Dopo il primo login:

1. Click sul nome "Amministratore" in alto a destra
2. Click su "Cambia password"
3. Vecchia password: `admin123`
4. Nuova password: scegli qualcosa di sicuro (≥8 caratteri)

---

## Comandi rapidi (dopo il primo setup)

Una volta tutto funzionante, per le sessioni successive:

```bash
cd ~/Projects/stoic-eln
source .venv/bin/activate
make run                # avvia l'app
# ... lavora ...
# Ctrl+C per fermare l'app
```

Altri comandi utili:

```bash
make test               # esegue i test
make lint               # controlla lo stile del codice
make format             # auto-formatta il codice
make help               # mostra tutti i comandi disponibili
```

---

## Risoluzione problemi

### "command not found: pybabel" o "flask"

Hai dimenticato di attivare il venv. Esegui:

```bash
source .venv/bin/activate
```

### "ModuleNotFoundError: No module named 'stoic_eln'"

Le dipendenze non sono installate. Dal venv attivo:

```bash
pip install -e ".[dev]"
```

### "Address already in use" alla porta 5000

Hai già un'altra istanza in esecuzione. Trova il processo e fermalo:

```bash
lsof -ti:5000 | xargs kill -9
```

Oppure usa un'altra porta:

```bash
flask --app stoic_eln run --debug --port 5001
```

### Il browser mostra "This site can't be reached"

Verifica che il server sia in esecuzione (terminal mostra "Running on http://...").
Prova `http://127.0.0.1:5000` invece di `localhost:5000`.

### Un errore Python che non capisco

Copia l'errore completo e mandamelo. Lo decifriamo insieme.

---

## Cosa c'è dentro Stoic ELN v2.0.0a1 (Settimana 1)

Sezione tecnica per i curiosi:

- **Application factory** in `stoic_eln/__init__.py` — pattern Flask production-ready
- **Modelli SQLAlchemy 2.x** in `stoic_eln/models/`: User (con Argon2 hashing),
  AuditLog, AppSetting
- **Auth blueprint** in `stoic_eln/blueprints/auth/` — login/logout/change password +
  switch lingua e tema
- **Main blueprint** in `stoic_eln/blueprints/main/` — dashboard
- **Audit service** in `stoic_eln/services/audit.py` — logging eventi
- **Code generator** in `stoic_eln/services/code_generator.py` — operator codes
- **Templates** in `stoic_eln/templates/` — Jinja2 + Bootstrap 5 + Lucide icons
- **CSS** in `stoic_eln/static/css/app.css` — design tokens via CSS variables, dark
  mode nativo
- **Traduzioni** in `stoic_eln/translations/` — IT (default) ed EN
- **Test** in `tests/` — pytest, ~15 test che coprono auth, modelli, smoke

Cosa NON c'è ancora (nelle prossime settimane):
- Sostanze + PubChem + GHS (Settimana 2)
- Inventario (Settimana 2)
- Reazioni + ReactionDrawer (Settimana 3)
- Esecuzione run (Settimana 4)
- Reports + admin + audit UI (Settimana 5)
- RPi deploy + release (Settimana 6)

---

Quando hai completato gli step 1-7 e vedi la dashboard funzionante, fammi sapere
con uno screenshot.
