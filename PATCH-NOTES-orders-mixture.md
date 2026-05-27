# Stoic ELN — Patch: Plan-order su Mixture commerciali

**Settimana 6, Patch 15** — Estensione del workflow `Order` per
supportare anche le miscele commerciali (HCl 12N, NaOH 1M, PBS pH 7.4,
ecc.) in aggiunta alle sostanze pure.

Primo task della **Fase 1 della roadmap v1.0** ("Completezza funzionale").

## Sintesi

Prima di questa patch, un `Order` poteva solo riferirsi a una `Substance`.
Ora un `Order` può riferirsi **o** a una `Substance` **o** a una `Mixture`
(XOR enforced via CHECK constraint). Il workflow lifecycle resta
identico (planned → ordered → received → InventoryItem creato): cambia
solo che l'InventoryItem risultante è un lotto-di-Mixture invece di un
lotto-di-Substance quando l'ordine è di una Mixture.

Caso d'uso primario (≈99.9%): acquisto di soluzioni commerciali pronte
all'uso (HCl 12N, NaOH 1M, PBS pH 7.4). Le miscele preparate in
laboratorio continuano a passare per il workflow `MixturePrep` (non
toccato).

## File toccati

### Modelli e servizi

- **`stoic_eln/models/order.py`** — Rilassato `substance_id` a
  nullable, aggiunto `mixture_id` nullable con FK a `mixture(id)`,
  aggiunto CHECK constraint XOR `ck_purchase_order_substance_xor_mixture`,
  aggiunti `kind` e `target_name` properties per uso nei templates.
  `target_name` per Mixture usa `display_label` (include la
  concentrazione, es. "HCl 12N (12 N)") così due miscele con lo
  stesso nome ma concentrazioni diverse restano distinguibili
  ovunque (lista, detail, dropdown).
- **`stoic_eln/services/order_service.py`** — `receive_order()` ora
  crea l'`InventoryItem` con `substance_id=order.substance_id` E
  `mixture_id=order.mixture_id`, replicando l'XOR. Gli altri metodi
  (`mark_as_ordered`, `cancel_order`) sono kind-agnostici e non
  cambiano.

### Routes

- **`stoic_eln/blueprints/orders/routes.py`**:
  - `list_view`: outer-join Substance + Mixture, filtro `q` cerca su
    entrambi i nomi.
  - `new`: accetta `?substance_id=N` o `?mixture_id=N` da query
    string; POST valida XOR (rifiuta both, rifiuta neither).
  - `edit`: blocca la modifica del target (substance_id/mixture_id
    immutabili) — il resto editabile come prima.
  - `detail`, `receive`: agnostici via `order.kind`.
  - `shopping_list_create_orders`: non toccato (la lista della spesa
    suggerisce solo riordini di Substance — auto-suggest di Mixture
    è enhancement futuro, non in scope qui).

### Templates

- **`stoic_eln/templates/orders/list.html`** — Header colonna da
  "Sostanza" a "Cosa"; nome target renderizzato via
  `order.target_name`; badge "miscela" per ordini di tipo mixture.
- **`stoic_eln/templates/orders/form.html`** — Picker kind-toggle
  (radio buttons) quando si crea un ordine nuovo senza pre-population;
  dropdown per ciascun kind con JS swap. Pre-population gestita
  separatamente per substance/mixture.
- **`stoic_eln/templates/orders/detail.html`** — Header e card
  dettagli adattati al kind (link a `substances.detail` o
  `mixtures.detail`).
- **`stoic_eln/templates/orders/receive.html`** — Header adattato al
  kind. Il form di ricezione vero e proprio è agnostico (quantità +
  cost + batch_code + expiry + location, identico per entrambi).
- **`stoic_eln/templates/mixtures/detail.html`** — Aggiunto pulsante
  "Pianifica ordine" nell'header pagina, accanto a "Prepara nuovo
  lotto", solo per miscele attive. Linka a `/orders/new?mixture_id=N`.

### Migration

- **`scripts/migrate_orders_mixture.py`** — Script idempotente che
  ricostruisce la tabella `purchase_order` con i nuovi vincoli (SQLite
  table-rebuild idiom — non supporta `ALTER COLUMN` per rilassare NOT
  NULL o aggiungere CHECK constraint in-place). Mantiene tutti i dati
  esistenti. Sicuro a rilanciare: skip se lo schema è già aggiornato.

### i18n

- **`stoic_eln/translations/en/LC_MESSAGES/messages.po`** — 9 nuove
  voci `msgid` + `msgstr` per le stringhe italiane introdotte da
  questa patch (es. "Cosa stai ordinando?" → "What are you ordering?",
  "Miscela commerciale" → "Commercial mixture", ecc.). Aggiunte
  manualmente in coda al file (workflow Stoic: niente `pybabel update
  --no-fuzzy-matching`).
- **`stoic_eln/translations/en/LC_MESSAGES/messages.mo`** e
  **`stoic_eln/translations/it/LC_MESSAGES/messages.mo`** —
  Ricompilati con `pybabel compile -d stoic_eln/translations` per
  riflettere le nuove traduzioni nell'app a runtime.

### Tests

- **`tests/test_orders_mixture.py`** — Nuova test suite, 10 test:
  - `test_order_xor_rejects_both` — IntegrityError se entrambi i FK
  - `test_order_xor_rejects_neither` — IntegrityError se nessuno
  - `test_order_kind_property` — `kind` e `target_name` corrette
  - `test_order_mixture_plan` — POST /orders/new?mixture_id crea
    Order kind=mixture
  - `test_order_mixture_full_lifecycle` — planned → ordered →
    received, lot ha `mixture_id` set
  - `test_order_mixture_partial` — received_partial preserva
    `mixture_id`
  - `test_order_mixture_cancel` — cancellazione funziona
  - `test_order_new_rejects_both_targets` — UI rifiuta both
  - `test_order_new_rejects_neither_target` — UI rifiuta neither
  - `test_order_list_shows_both_kinds` — /orders/ lista entrambi

## Applicazione della patch

Da `~/Projects/stoic-eln/`:

```
tar -xzvf stoic-orders-mixture-patch.tar.gz
.venv/bin/python scripts/migrate_orders_mixture.py
.venv/bin/pytest tests/ -q
.venv/bin/pytest tests/test_orders_mixture.py -v
```

Atteso:
- Migration: `purchase_order rebuilt: substance_id nullable, mixture_id added, XOR check added`
- Test suite completa: 490/490 passed (480 pre-patch + 10 nuovi)
- Test suite specifica: 10/10 nuovi test verdi

## Backward compatibility

Tutti i 480 test pre-esistenti continuano a passare senza modifiche.
I 7 test esistenti su `Order` (in `test_run_setup.py`) usano la forma
`Order(substance_id=...)` che è ancora valida (XOR soddisfatto perché
`mixture_id` resta NULL).

I dati pre-esistenti nella tabella `purchase_order` sono preservati
dalla migration. Gli ordini storici continuano a comportarsi come
prima — restano "ordini di Substance" e creano lotti-di-Substance
quando ricevuti.

## Cosa NON è in questa patch

- **Cascade scarico inventario per Mixture-as-component** (prossimo task
  Fase 1). Questa patch tratta l'**acquisto** di Mixture commerciali;
  il **consumo** di Mixture come precursore in altre prep è coperto già
  da `prep_service` ma andrà raffinato nel prossimo task.
- **Auto-suggerimento di Mixture nella shopping list**. La shopping list
  attualmente suggerisce solo Substance. Aggiungere Mixture richiede un
  modello di "minimum threshold per Mixture" che non esiste ancora.
- **Modifica del kind dopo creazione**. Un ordine creato come substance
  resta substance per sempre; lo stesso per mixture. Per cambiare,
  l'utente annulla l'ordine e ne crea uno nuovo.
