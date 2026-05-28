# Stoic ELN — Patch: prep_service cascade per child_mixture components

Estende `prep_service` per supportare ricette in cui un componente è
un'altra Mixture (`child_mixture` invece di `substance`).

Caso d'uso canonico: preparazione di HCl 6N a partire da HCl 12N
(commerciale). Nella ricetta di HCl 6N il solute è la child_mixture
"HCl 12N", non la substance "HCl".

## Bug risolto

Pre-patch: `prepare_form` di una mixture che usava un child_mixture
component crashava con:

```
AttributeError: 'NoneType' object has no attribute 'name'
  File ".../prep_service.py", line 655, in suggest_consumptions
    substance_name=comp.substance.name,
```

Il codice assumeva che `comp.substance` fosse sempre valorizzato, ma
nei mixture-as-component è `None` (è `comp.child_mixture` ad essere
settato, XOR).

## Bug latente aggiuntivo fixato

Durante il test sul Mac è emerso un secondo `TypeError` nella stessa
chiamata, dopo il fix del primo:

```
TypeError: can't compare datetime.datetime to datetime.date
  File ".../prep_service.py", line 188, in _candidate_lots
    rows.sort(
        key=lambda r: (r.purchased_at or r.created_at, r.id),
```

`InventoryItem.purchased_at` è `Date`, `InventoryItem.created_at` è
`DateTime`. Quando in un sort key si mescolano i due tipi (un lotto
con `purchased_at` settato + un lotto con `purchased_at=None` che
ricade su `created_at`) Python esplode. Bug **pre-esistente** —
non introdotto dal cascade — ma più facile da triggerare ora che
i candidate set sono più ampi (mixture lots inclusi).

Fix: usare `date.min` come fallback per i lotti senza `purchased_at`
(stesso pattern già in `shopping_list.py`). I lotti senza data di
acquisto finiscono in fondo alla lista candidate invece di ordinare
per `created_at`. Più onesto: se l'utente non sa quando il lotto è
stato acquistato, lo dichiariamo "data sconosciuta = ultimo".

## Decisioni di design

1. **Stock concentration da `child_mixture.primary_concentration`**.
   Diretto, senza fallback chain. Se manca, è un errore di configura-
   zione del catalogo e il chimico la deve sistemare. Niente magia
   nascosta.
2. **Cascade 1-livello**: consuma solo il lotto direttamente puntato
   dal child_mixture component. Niente ricorsione: il lotto puntato è
   già un oggetto fisico autonomo nel magazzino, la sua ancestry era
   già stata regolata al momento della sua preparazione.
3. **Lotti insufficienti**: `ValueError`, identico al pattern già
   esistente per substance lots.

## File toccati

### Service

- **`stoic_eln/services/prep_service.py`**
  - `SuggestedConsumption`: campo `substance_id` rilassato a
    `int | None`, aggiunto `mixture_id: int | None`, aggiunto
    `display_name: str` (sostituisce semanticamente `substance_name`,
    che resta come property alias per backward compat con i template).
    Aggiunte `substance_name` property (alias) e `is_mixture` property.
  - Nuova funzione `_candidate_lots_for_mixture(mixture_id, want_unit)`:
    cerca lotti DI una mixture (non "contenenti").
  - Nuova funzione `_candidates_for_component(comp, want_unit)`:
    dispatcher che route a `_candidate_lots` o
    `_candidate_lots_for_mixture` in base a `comp.is_mixture_component`.
  - Nuova funzione `read_stock_for_child_mixture(lot, child_mixture)`:
    legge la stock concentration da `child_mixture.primary_concentration`.
  - Loop `suggest_consumptions` refactored: usa il dispatcher per
    pre-calcolare i candidates, distingue tra substance solute e
    child_mixture solute nel ramo dilution, usa `comp.display_name`
    invece di `comp.substance.name` ovunque, popola `mixture_id` e
    `display_name` nelle `SuggestedConsumption` risultanti.

### Routes

- **`stoic_eln/blueprints/mixtures/routes.py`** — `recompute_prep_row`
  ora dispatcha tra `read_stock_for_solute` e
  `read_stock_for_child_mixture` in base al kind del component.

### Templates

- **`stoic_eln/templates/mixtures/prepare.html`** — Lista componenti
  usa `c.display_name` (gestisce sia substance che child_mixture).
  Aggiunto badge "miscela" per i child_mixture components.
- **`stoic_eln/templates/mixtures/_prep_rows.html`** — Usa
  `r.display_name` + badge "miscela" per `r.is_mixture`.

### Tests

- **`tests/test_prep_service_child_mixture.py`** — Nuova suite, 8 test:
  - `test_suggest_renders_without_attribute_error_for_child_mixture_recipe`
    — il bug originale è fixato
  - `test_suggest_finds_child_mixture_lot_as_candidate` — trova lotti
    DI HCl 12N, non lotti contenenti HCl substance
  - `test_suggest_dilution_math_uses_child_mixture_primary_concentration`
    — 500 mL × 6/12 = 250 mL di HCl 12N, 250 mL di acqua
  - `test_suggest_stock_info_includes_child_mixture_name` — stock info
    mostra "12 N (HCl 12N)"
  - `test_read_stock_for_child_mixture_uses_primary_concentration` —
    unit test dell'helper
  - `test_read_stock_for_child_mixture_missing_primary_returns_missing`
    — graceful degradation per misconfig
  - `test_consume_deducts_from_child_mixture_lot` — esecuzione prep
    scarica il lotto di HCl 12N di 250 mL (cascade 1-livello)
  - `test_consume_raises_on_insufficient_child_mixture_lot` —
    ValueError consistente con substance behaviour

### i18n

Nessuna nuova traduzione necessaria. La sola stringa IT introdotta
("miscela" usata nel badge) era già presente nel `.po` EN da patch
precedenti.

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-prep-cascade-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: 504 passed (496 pre-patch + 8 nuovi). Niente migration: la
patch tocca solo logica di servizio, route, template e test. Nessuna
modifica al modello.

## Backward compatibility

- `SuggestedConsumption.substance_name` property mantenuta come alias
  di `display_name` → i template che leggono `r.substance_name`
  continuano a funzionare senza modifiche.
- `SuggestedConsumption.substance_id` resta presente; ora opzionale,
  ma per ricette substance-only continua a essere valorizzato come
  prima.
- I 19 test esistenti di `test_prep_service.py` continuano a passare
  senza modifiche.
- `read_stock_for_solute()` immutata: continua a essere usata per i
  substance solutes, accanto alla nuova `read_stock_for_child_mixture`.

## Cosa NON è in questa patch

- **Cascade ricorsiva**: out of scope per decisione. Solo il lotto
  child_mixture diretto viene scaricato.
- **Auto-detect di "non c'è abbastanza in ancestor lots"**: non viene
  fatta nessuna validazione cross-livello. Se hai HCl 6N preparata da
  HCl 12N e HCl 12N è esaurita, l'uso di HCl 6N continua a funzionare
  finché ci sono lotti di HCl 6N attivi nel magazzino.
- **UI per creare ricette con child_mixture component**: il form di
  creazione/modifica mixture probabilmente già supporta la creazione
  di child_mixture components (lo deduco dal fatto che il bug è stato
  triggerato da una mixture reale con child_mixture). Da verificare
  visivamente sul Mac.
