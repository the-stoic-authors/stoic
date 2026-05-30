# Stoic ELN — Patch: politica unità g/mL in inventario

Fix di un bug emerso durante il collaudo della Fase 1 e
introduzione di una **politica forte** per garantire la coerenza
tra grammi e millilitri nei lotti di magazzino.

## Bug originale

Nel form di Edit lot di una sostanza liquida con densità nota
(esempio: Hexanoyl chloride, density=0.9763 g/mL):

1. L'operatore inseriva 100 g (la quantità comprata, espressa in
   massa) lasciando `quantity_mL` vuoto.
2. Nelle reazioni il sistema dosa Hexanoyl chloride in mL (perché
   è liquido con densità nota → `target_volume_mL = mass / density`).
3. Quando la run prova a consumare X mL, trova
   `lot.quantity_mL = NULL` e fallisce con
   "0 mL disponibili, richiesti X mL".

Il magazzino era de facto incoerente: stessa bottiglia, due
contatori indipendenti (g e mL), uno solo popolato.

## Politica introdotta

Una matrice unica decide quali unità sono editabili per un lotto
in funzione della sostanza:

| Sostanza | `is_solvent` | `density` | Unità editabili |
|---|---|---|---|
| Reagente solido / liquido senza densità | False | NULL | **solo g** |
| Reagente con densità | False | settata | **g + mL sincronizzati** |
| Solvente senza densità | True | NULL | **solo mL** |
| Solvente con densità | True | settata | **g + mL sincronizzati** |

**Invariante chiave**: per ogni `InventoryItem`, `quantity_g` e
`quantity_mL` (e analogamente la coppia `initial_*`) o
rappresentano la stessa quantità fisica (sincronizzate via
densità), o esattamente uno dei due è popolato e l'altro è NULL.
Due valori indipendenti significherebbero contare la stessa
bottiglia due volte.

I lotti di **mixture** non sono soggetti alla matrice: la ricetta
già vincola il comportamento e non tutte le mixture hanno una
densità. Per loro vale la politica permissiva di prima.

## File toccati

### Service nuovo

- **`stoic_eln/services/inventory_quantity.py`** — Fonte di verità
  della matrice. Espone:
  - `policy_for_substance(sub)` → `UnitPolicy` con `allow_g`,
    `allow_mL`, `synced`, `density`
  - `normalize_pair(g, mL, policy)` → normalizza una coppia
    (propaga via densità, rifiuta unità non consentite, valida
    coerenza con tolleranza 0.5%)
  - `normalize_inventory_quantities(...)` → normalizza entrambe le
    coppie initial/remaining

### Routes

- **`stoic_eln/blueprints/inventory/routes.py`**:
  - Sia `create` che `edit` calcolano `unit_policy` all'inizio
    (passata al template per la disabilitazione condizionale dei
    campi) e applicano `normalize_inventory_quantities` prima di
    salvare.
  - Su errore (es. mL inserito su un reagente senza densità,
    valori incoerenti, ...) il form viene ri-renderizzato con
    flash message specifico, niente write parziale.

### Template

- **`stoic_eln/templates/inventory/form.html`**:
  - 4 hint diversi nella sezione Quantità in base al caso della
    matrice (solido, reagente+densità, solvente senza, solvente+
    densità). Per il caso "solvente senza densità" un alert con
    link diretto a Modifica sostanza per aggiungere la densità.
  - I campi non consentiti sono renderizzati con `disabled`.
  - Quando il caso è "sincronizzato", uno script inline (~30
    righe, niente librerie) bilancia i due input via densità ad
    ogni `input`, sia per la coppia initial sia per la coppia
    remaining.

### Migration script

- **`scripts/migrate_inventory_quantity_policy.py`** — Da lanciare
  una volta dopo l'applicazione della patch, percorre tutti gli
  active `InventoryItem` e per ogni lotto di sostanza con densità
  nota propaga il valore mancante. Idempotente, sicuro re-lanciarlo.
  Riporta a fine esecuzione un sommario:
  - quanti lotti scansionati
  - quanti già coerenti
  - quanti fixati (propagazione)
  - eventuali lotti con coppie incoerenti (non modificati, da
    rivedere a mano)

### Tests

- **`tests/test_inventory_quantity_policy.py`** (nuovo) — 22 test:
  - 6 sulla classificazione `UnitPolicy` (4 casi della matrice +
    `None` substance + densità zero)
  - 12 su `normalize_pair` / `normalize_inventory_quantities`
    (auto-fill nei dual-synced, rifiuto mL sui reagenti senza
    densità, rifiuto g sui solventi senza densità, coppia
    coerente/incoerente, coppia vuota)
  - 4 smoke test sulle route (create con sostanza con densità →
    auto-fill mL, create rifiuto mL su reagente senza densità,
    create rifiuto g su solvente senza densità, create rifiuto
    coppia incoerente)

- **`tests/test_substances.py`** — Test pre-esistente
  `test_inventory_add_lot` aggiornato per riflettere la nuova
  regola: "EtOH" ora è marcato `is_solvent=True` (com'è nella
  pratica), così il test può inserire `initial_quantity_mL=1000`
  e passare. Prima il test si appoggiava al comportamento
  permissivo di "qualsiasi sostanza accetta mL", non più valido.

### i18n

- 3 nuove entry EN nel `messages.po` per i nuovi hint nel template
  inventario. `.mo` ricompilati.

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-inventory-quantity-policy-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **549 passed** (527 pre-patch + 22 nuovi).

### Migration dei dati esistenti

Dopo aver lanciato `make test` ed essersi assicurati che tutto sia
verde, eseguire una volta sola:

```
cd ~/Projects/stoic-eln
.venv/bin/python -m scripts.migrate_inventory_quantity_policy
```

Output atteso: un sommario con il conteggio dei lotti scansionati,
quelli fixati (propagazione via densità), e quelli con coppie
incoerenti da rivedere a mano. Il lotto di Hexanoyl chloride
emerso durante il collaudo dovrebbe apparire come "fixed".

## Cosa NON è in questa patch

- **Modifica della `density` sulla scheda Substance dal form
  dell'inventario**: se l'utente scopre che la densità è sbagliata,
  va a modificarla nella pagina Edit della Substance. Coerente
  con la separazione delle responsabilità (un lotto sa quanto
  materiale ha, la substance sa le proprietà fisiche del composto).
- **Cancellazione che azzera anche la `density` sulla substance**:
  troppo invasivo, era stato discusso ma scartato — la cancellazione
  di un valore in un lotto con politica sincronizzata semplicemente
  azzera anche l'altro valore lato JS.
- **Auto-detection di `is_solvent`** in base alla densità o ad
  altre proprietà: resta un flag esplicito sulla substance.
