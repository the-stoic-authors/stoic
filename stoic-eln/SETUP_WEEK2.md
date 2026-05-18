# Stoic ELN — Aggiornamento alla Settimana 2

Questa guida descrive come passare dalla Settimana 1 alla Settimana 2 del progetto.
La Settimana 2 aggiunge: gestione sostanze, integrazione PubChem, frasi GHS, e
inventario lotti.

---

## Cosa c'è di nuovo

### Catalogo sostanze
- Lista paginata con ricerca live (HTMX) su nome, IUPAC, CAS, formula, e codice lotto
- Detail page con tutte le proprietà (identificatori, fisiche, GHS, lotti)
- Creazione manuale + modifica
- Deactivation soft (i run storici la mantengono visibile)
- Detect duplicati via InChIKey

### Importa da PubChem
- Cerca per nome, CAS, SMILES, InChI, InChIKey, o CID con auto-detect
- Anteprima dei dati prima di importare
- Cache in-memory (TTL 24h) per evitare chiamate ripetute
- Estrae proprietà fisiche (MP, BP, densità) e GHS (pittogrammi + frasi H/P)

### Inventario (lotti)
- Vista magazzino con ricerca incrociata (substance + batch)
- Aggiunta/modifica lotti per ciascuna sostanza
- Tracking quantità iniziale + residua (g o mL)
- Costo totale + costo per unità calcolato
- Campo posizione fisica libero (es. "Armadio 3, ripiano alto")
- Date di acquisto e scadenza

### Sicurezza GHS
- 9 pittogrammi GHS (GHS01-GHS09) inclusi
- 106 frasi H/P/EUH dal CLP Regulation con testi ufficiali in IT e EN
- Scheda di sicurezza (SDS) stampabile, layout A4

### Seed data
- 31 sostanze comuni precaricate al primo avvio (acqua, etanolo, MeOH, DCM,
  toluene, THF, DMF, DMSO, basi, acidi, catalizzatori, ecc.)

---

## Come applicare l'aggiornamento

### Step 1 — Backup del database (consigliato)

Se hai dati da preservare nel database (es. utenti aggiunti, password cambiate):

```bash
cd ~/Projects/stoic-eln
cp stoic_eln.db stoic_eln.db.backup-week1
```

### Step 2 — Estrai il nuovo tarball sopra il progetto

```bash
cd ~/Projects/stoic-eln
tar -xzf ~/Downloads/stoic-eln-week2.tar.gz
```

Il tar sovrascrive i file esistenti e crea quelli nuovi. La struttura è
identica alla Settimana 1, quindi non serve scegliere una directory diversa.

### Step 3 — Installa le nuove dipendenze

Sono state aggiunte: `httpx` (chiamate HTTP a PubChem), `cachetools` (cache
in-memory), `respx` (mocking HTTP nei test).

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

L'installazione dovrebbe completarsi in ~30 secondi.

### Step 4 — Reset e ri-init del database (consigliato)

Lo schema è cambiato (3 nuove tabelle: `substance`, `inventory_item`,
`hazard_phrase`). Il modo più pulito è fare un reset:

```bash
python scripts/init_db.py --reset
```

Output atteso:

```
Dropping all tables...
Creating tables...
Admin user created: admin / admin123
Change this password immediately after first login!

Loading seed data...
  hazard_phrases: added=106 skipped=0
  substances: added=31 skipped=0

Done. Run the app with: flask --app stoic_eln run --debug
```

**Nota:** `--reset` cancella tutti gli utenti e le password personalizzate. Se
hai dati da preservare, salta `--reset` e usa solo `python scripts/init_db.py`
— l'init è idempotente, aggiunge solo schema e seed mancanti.

### Step 5 — Compila le traduzioni aggiornate

```bash
pybabel compile -d stoic_eln/translations
```

### Step 6 — Avvia l'app

```bash
flask --app stoic_eln run --debug
# oppure
make run
```

Apri `http://127.0.0.1:5000/` e fai login con `admin / admin123`.

---

## Cosa testare

### Catalogo sostanze
1. Sidebar → click su **Sostanze** (la voce è ora attiva, non grigiata)
2. Dovresti vedere ~31 sostanze precaricate (Methanol, Ethanol, DCM, ecc.)
3. Cerca **etoh** → filtri vivi via HTMX (300ms debounce)
4. Cerca **64-17-5** (CAS dell'etanolo) → trova Ethanol
5. Click su una sostanza → detail page con identificatori, GHS, lotti

### Inventario
1. Da una sostanza qualsiasi, click **+ Aggiungi lotto**
2. Compila batch_code, fornitore, quantità, posizione (es. "Armadio 3, ripiano alto")
3. Salva → torni al detail con il lotto visibile
4. Sidebar → **Inventario** → vedi il lotto nel magazzino
5. Cerca per batch_code, supplier, posizione, sostanza, CAS — tutto funziona

### PubChem import
1. Sostanze → **Importa da PubChem**
2. Esempi:
   - Nome: `caffeine`
   - CAS: `50-78-2` (aspirin)
   - SMILES: `CN1C=NC2=C1C(=O)N(C(=O)N2C)C` (caffeina)
   - InChIKey: `RYYVLZVUVIJVGH-UHFFFAOYSA-N` (caffeina)
3. Anteprima → conferma → la sostanza viene importata con tutti i dati disponibili

   **Nota:** PubChem a volte ha dati incompleti, soprattutto GHS per sostanze rare.
   Dopo l'import puoi sempre completare con la voce **Modifica**.

### SDS stampabile
1. Da una sostanza con dati GHS (es. Ethanol) → click **SDS**
2. Si apre in una nuova tab con layout pulito
3. Click **Stampa** → preview di stampa A4

### Cambio tema
1. Toggle tema (sole / luna / monitor)
2. I pittogrammi GHS rimangono leggibili (rosso + nero su bianco) in entrambi i temi
3. Tutto il resto si adatta correttamente

---

## Cosa non c'è ancora (in arrivo)

- **Disegno strutture** (SmilesDrawer 2.x integration) — Settimana 3
- **Reazioni** + tabella reagenti + stoichiometric calculator — Settimana 3
- **Esecuzione run** + auto-deduzione inventario — Settimana 4
- **Reportistica** + admin UI per audit log — Settimana 5
- **Deploy RPi** + release v2.0.0 — Settimana 6

---

## Risoluzione problemi

### "ModuleNotFoundError: No module named 'httpx'"

Hai dimenticato lo step 3 (`pip install -e ".[dev]"`).

### Pittogrammi GHS appaiono come 404 nel Network panel

Verifica che esistano:
```bash
ls stoic_eln/static/img/ghs/
# Dovrebbero esserci GHS01.svg fino a GHS09.svg
```

### Le traduzioni nuove non appaiono in EN

Hai dimenticato di compilare:
```bash
pybabel compile -d stoic_eln/translations
```

### "no such table: substance" all'apertura della pagina sostanze

Il database non ha lo schema aggiornato. Fai:
```bash
python scripts/init_db.py
# (senza --reset, è idempotente)
```

### PubChem non risponde / timeout

PubChem ha rate limit ed è gratuito. Errori temporanei ~5xx capitano. Il
service mostra l'errore al primo tentativo, basta riprovare. La cache locale
TTL 24h evita di ricaricare dati già visti nella stessa sessione.

### Le ricerche HTMX non funzionano

Verifica che HTMX sia caricato:
- Apri il browser DevTools → Console → controlla se ci sono errori
- Network panel → cerca una request a `/substances/?q=...` con header
  `HX-Request: true`

---

## Test e verifica

```bash
make test    # esegue tutti i 46 test (15 Settimana 1 + 31 Settimana 2)
make lint    # controlla lo stile del codice
```

Tutti dovrebbero passare. Se non passano, copiami l'output e lo decifriamo.

---

## Sviluppo continuo

Le sessioni successive sono come prima:

```bash
cd ~/Projects/stoic-eln
source .venv/bin/activate
make run
# Ctrl+C per fermare
```

---

Quando l'aggiornamento è in piedi e hai testato i punti sopra, fammi sapere e
passiamo alla **Settimana 3** (Reazioni + SmilesDrawer + tabella reagenti).
