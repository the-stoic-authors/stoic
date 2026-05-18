# Stoic — patch 15.2.1 (seed delle 30 sostanze comuni)

Aggiunge uno script di seeding per popolare il database con 30
reagenti standard di un laboratorio di chimica organica: solventi,
acidi/basi inorganici, agenti disidratanti, sali da banco.

## Le 30 sostanze

**Solventi alogenati (2)**:
diclorometano, cloroformio

**Solventi eterei (2)**:
etere etilico, tetraidrofurano

**Solventi esteri / chetoni / aromatici / alifatici (5)**:
acetato di etile, acetone, toluene, esano, etere di petrolio (40–60 °C)

**Solventi alcolici (3)**:
metanolo, etanolo assoluto, isopropanolo

**Solventi polari aprotici (3)**:
DMSO, DMF, acetonitrile

**Acidi (4)**:
HCl gas, acido solforico 98 %, acido nitrico 65 %, acido acetico
glaciale

**Basi (3)**:
NaOH, KOH, ammoniaca 25 %

**Sali / tamponi (3)**:
Na₂CO₃, NaHCO₃, NaCl

**Agenti disidratanti (2)**:
Na₂SO₄ anidro, MgSO₄ anidro

**Altri (3)**:
Na₂S₂O₃, silice gel 60, acqua deionizzata

Totale: **30**.

## Dati inclusi per ogni sostanza

- Nome italiano + nome IUPAC inglese
- CAS, formula molecolare, peso molecolare
- SMILES + InChI + InChIKey (eccetto miscele tipo PE)
- Densità a 20 °C (per liquidi)
- Stato fisico (solid / liquid / gas)
- `is_solvent = True` per i solventi (così appaiono nei picker)
- Punto di fusione / ebollizione
- GHS pittogrammi + frasi H + frasi P principali (curati su SDS
  Sigma-Aldrich/TCI, union conservativa quando differiscono)
- PubChem CID per import incrementale futuro
- Note specifiche quando rilevanti (es. NH₃ è in soluzione 25 %,
  silice è 60 mesh)

## Comportamento

**Idempotente.** Lookup per CAS number prima, fallback per nome.
Una sostanza già presente è skippata (non sovrascritta, così le
modifiche manuali sono preservate).

**Dry-run supportato.** `--dry-run` mostra cosa farebbe senza
toccare il DB. Utile per preview prima del commit.

**Conservativo sulle frasi H/P.** Includo solo le frasi principali
(le H3xx in generale + alcune H2xx critiche per infiammabilità).
Le SDS reali contengono 20+ frasi a sostanza; il seed dà un
punto di partenza ragionevole che l'utente può estendere via
import PubChem se vuole dati più ricchi.

## File aggiunti

- `scripts/seed_common_substances.py` (~470 righe)
- `tests/test_seed_common_substances.py` (7 test)

Nessuna modifica al codice esistente, nessuna migrazione DB.

## Test

7 nuovi test in `tests/test_seed_common_substances.py`:
- Inserimento su DB vuoto
- Idempotenza
- Dry-run senza side effect
- Sanity check (campi obbligatori presenti)
- Validazione RDKit di tutti i SMILES seedati
- Spot check acqua (nome, formula, smiles)
- Spot check NaOH (GHS05 + H290 + H314)

Suite totale: **487/493** verde (+7 nuovi, 6 legacy reactions
noti restano).

## Applicazione

```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-eln-patch15.2.1.tar.gz -C ~/Projects/
```

Nessun reinstall necessario (è solo uno script standalone +
test).

## Uso quando vorrai "ripulire" il DB

Workflow completo per passare da DB di test → DB di produzione:

```bash
cd ~/Projects/stoic-eln

# 1. Backup precauzionale dello stato attuale di test
cp instance/stoic_eln.db instance/stoic_eln.db.test-backup-$(date +%Y%m%d)

# 2. Stop il server se gira
.venv/bin/stoic stop 2>/dev/null   # ok se "not running"
# (oppure Ctrl+C nella finestra make run)

# 3. Wipe completo
rm instance/stoic_eln.db

# 4. Reinit schema vuoto
.venv/bin/python -m flask init-db

# 5. Ricrea primo admin (interattivo)
.venv/bin/python -m flask create-user --admin

# 6. Seed delle 30 sostanze
.venv/bin/python scripts/seed_common_substances.py

# 7. Verifica
.venv/bin/stoic status
.venv/bin/stoic start --foreground
```

Apri http://127.0.0.1:5001 — vai su Sostanze → ne dovresti
trovare 30, con pittogrammi, formule, SMILES e proprietà
fisiche già compilati.

## Dry-run (anteprima prima di applicare)

```bash
.venv/bin/python scripts/seed_common_substances.py --dry-run
```

Mostra cosa farebbe senza toccare il DB. Sicuro su DB di
produzione: zero side effect.

## Cosa NON viene seedato

- **Utenti**: solo l'admin che hai creato manualmente. Gli altri
  utenti li aggiungi tu in Settings → Utenti.
- **Gruppi**: il default group "L" viene creato da `init-db`;
  altri gruppi li crei in base alla struttura del tuo lab.
- **Lotti di inventario**: niente. Le sostanze sono catalogate
  ma "vuote" — aggiungi i lotti reali quando arrivano in
  laboratorio (con costo, CAS del fornitore, data di acquisto,
  ecc.).
- **Reazioni / preparazioni / run**: nessuna. Tu inizi a
  registrarli quando inizi a lavorare.
- **Miscele**: nessuna. Le crei tu (es. HCl 12N, EtOAc/PE 5:3)
  quando le prepari.

Quindi dopo il seed hai un "catalogo sostanze" pronto, e tutto
il resto è il tuo lavoro reale che si accumula nel tempo.

## Customizzazione

Se vuoi aggiungere altre sostanze al seed (es. reagenti
specifici della tua chimica), modifica
`scripts/seed_common_substances.py`, sezione
`COMMON_SUBSTANCES`. Aggiungi una dict per ogni sostanza
seguendo lo stesso pattern, poi rilancia lo script:
quelle nuove vengono aggiunte, le esistenti rispettate.

Per export di sostanze esistenti dal tuo DB in formato
"seed-style" (per condividere il tuo catalogo), può essere
una feature futura. Per ora lo script è solo
"insert dei 30 standard".
