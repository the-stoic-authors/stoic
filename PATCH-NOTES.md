# Stoic — patch 14.6.9 (fix 6 legacy test reactions → 0 fail)

Chiude i 6 fail nella suite di test ereditati dalla 13.5 quando
l'architettura dei components delle reazioni è stata refactorata.
**Suite ora 486/486 verde, 0 fail noti.**

## Bug funzionale chiuso (Parte A)

`stoic_eln/services/step_calc.py` — la funzione
`compute_step_component` ora gestisce due `ratio_kind` che erano
**offerti nell'UI ma non implementati nel backend**:

- **`absolute_mL`**: volume fisso, indipendente dal reference
  (es. "lava con 30 mL di acqua", "estrai con 20 mL EtOAc").
  Output: `mL = ratio_value`, deriva g da density, mmol da MW.
- **`absolute_g`**: massa fissa, stessa logica per i solidi
  (es. "aggiungi 2.5 g di Na₂SO₄ come disidratante").
  Output: `g = ratio_value`, deriva mL da density, mmol da MW.

Prima di questa patch: l'utente sceglieva "mL fissi" o "g fissi"
nella tendina del template step e il calcolo non avveniva
(StepQuantity con tutti None). Era effettivamente un bug
half-implemented dell'UI.

Docstring di `compute_step_component` aggiornata per elencare
tutti i 6 ratio_kind validi: `eq`, `mL_per_g`, `mL_per_mmol`,
`percent_vv`, `absolute_mL`, `absolute_g`.

## Test riscritti (Parte B)

I 4 test in `tests/test_reactions.py` testavano la **vecchia**
architettura ("amount_g salvati nel template", "field='amount_g'
nell'edit endpoint"). L'architettura attuale (subentrata nella
13.x) è draft-then-save + template-level equivalents only:

- I template hanno `equivalents` come parametro stoichiometrico,
  e basta. `amount_g`, `amount_mL`, `amount_mmol` sono
  intenzionalmente `None` nei template — sono calcolati a
  livello di Run dalla scala × equivalents.
- `POST /reactions/new` crea un draft vuoto. Non legge form data.
- `POST /reactions/<id>/save` accetta i field header e promuove
  draft → published, normalizzando il `template_code` (es. "MNR"
  diventa "MNR.1" la prima versione).
- `POST /reactions/components/<id>/edit` accetta SOLO i field
  template-level: `equivalents`, `concentration_M`, `is_limiting`.
  Altri field → 400 by design.

### Test riscritti

**`test_reaction_create_post`** — copre il workflow due step:
new → save, con verifica di `status='published'` finale e
normalizzazione di `template_code`.

**`test_add_component`** — verifica che dopo aggiunta:
- `substance_id`, `role`, `equivalents` siano salvati
- `amount_g`, `amount_mmol`, `amount_mL` siano `None`
  (template-level, non popolati a questo livello)
- il primo SM diventi auto-limiting con `eq=1`

**`test_add_component_with_equivalents_uses_limiting_mmol`** —
verifica che un secondo component (catalyst) con `eq=0.05` salvi
proprio `0.05` come equivalents (non un mmol derivato), non sia
limiting, e non abbia amount assoluti.

**`test_edit_component_inline`** — verifica che:
- editare `equivalents` su un non-limiting funzioni
- editare `amount_g` venga rifiutato con 400 (campo run-level)

## Suite

**486 passed in 135s, 0 failed, 0 skipped.**

Prima: 480 passed, 6 failed.
Dopo: 486 passed, 0 failed.

I 6 fail erano:
- `test_step_calc_absolute_mL` ✓ (fix backend)
- `test_step_calc_absolute_g` ✓ (fix backend)
- `test_reaction_create_post` ✓ (test riscritto)
- `test_add_component` ✓ (test riscritto)
- `test_add_component_with_equivalents_uses_limiting_mmol` ✓ (riscritto)
- `test_edit_component_inline` ✓ (riscritto)

## File modificati

- `stoic_eln/services/step_calc.py` — +33 righe (2 ratio_kind +
  docstring)
- `tests/test_reactions.py` — 4 test riscritti

Nessuna modifica DB, nessuna nuova dipendenza.

## Applicazione

```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-eln-patch14.6.9.tar.gz -C ~/Projects/

# Commit
git add .
git commit -m "patch 14.6.9: fix 6 legacy reaction tests (suite 486/486 verde)"
```

Niente da reinstallare, niente da migrare.

## Verifica

```bash
.venv/bin/pytest tests/ -q
```

Atteso: `486 passed in ~2:15`. Zero fail.

## Impatto utente

Funzionalmente: nel workflow di creazione di un **template di
step** (`/reactions/<id>` editing), selezionare "mL fissi" o
"g fissi" come tipo di ratio ora **funziona davvero** — il
valore inserito viene usato come quantità assoluta nelle Run
successive, indipendentemente dalla scala del run. Prima di
questa patch il valore era ignorato silenziosamente.

Caso d'uso tipico: nei work-up dove la quantità di reagente è
"di procedura" (es. "wash con 30 mL di brine") e non
stoichiometrica.

## Prossimi step Settimana 7

Con 0 fail noti, lo state è pronto per il public release:

- **15.3** — `install-linux.sh` per Debian/Ubuntu/Pi
- **15.4** — Push pubblico `the-stoic-authors/stoic` + release
  v1.0.0
- Backlog feature (non bloccanti):
  - "Pianifica ordine" per miscele commerciali
  - `prep_service` mixture-as-component scarico inventario
