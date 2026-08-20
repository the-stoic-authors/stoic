# Patch v1.4.4 — i componenti di step consumano l'inventario

## Il bug

`run_cost.py` contava i componenti di step (workup, estrazione,
cromatografia) nel costo del run. `use_quantity()` invece veniva
chiamato solo in `start_run()`, e solo sui `run.components` principali.

Risultato: il DCM di un'estrazione e l'eluente di una colonna avevano
un prezzo ma non un consumo. L'inventario non scendeva mai.

## Perché non basta dedurre a `start_run()`

I componenti principali si dichiarano prima: scrivi le masse, premi
Avvia, `start_run()` scala tutto in un colpo, e da lì la route rifiuta
altre modifiche. Una deduzione sola per componente basta.

Gli step no. `set_step_actual` accetta modifiche in `draft` **e** in
`in_progress` per progetto — non sai in anticipo quanti mL di DCM
prenderà la colonna. Ad `Avvia` quei valori spesso non esistono ancora,
e dopo cambiano più volte.

## La soluzione: deduzione incrementale

Ogni componente di step ricorda quanto ha già preso e da quale lotto.
A ogni modifica si muove solo la differenza:

| Situazione | Effetto sul lotto |
|---|---|
| dichiari 50 mL, preso 0 | preleva 50 |
| correggi a 40 mL, preso 50 | restituisce 10 |
| cambi lotto | restituisce tutto al vecchio, preleva dal nuovo |
| svuoti il campo | restituisce tutto |
| ri-salvi lo stesso valore | nessun movimento (idempotente) |

Due regole di dominio dietro l'implementazione:

1. **In draft non si consuma niente.** In bozza stai pianificando,
   esattamente come i componenti principali che muovono stock solo ad
   Avvia. La deduzione parte da `start_run()` — che recupera le
   quantità di step già compilate in bozza — e resta viva per tutto
   `in_progress`.
2. **Non si blocca mai, si registra.** Una quantità di step è un fatto
   già avvenuto al banco: rifiutarne la registrazione sarebbe sbagliato.
   Se il lotto non basta, viene azzerato (mai negativo), la quantità
   dichiarata resta intatta, e la discrepanza esce come warning — di
   solito è un residuo non registrato o un lotto sbagliato.

## Cosa cambia nel codice

- **Modello** — `RunStepComponent` guadagna `deducted_lot_id`,
  `deducted_mass_g`, `deducted_volume_mL`. `deducted_lot_id` è un
  `Integer` semplice, non una `ForeignKey`: SQLite non aggiunge FK a
  una tabella esistente senza rebuild, e il precedente in casa è
  `InventoryItem.source_run_id`.
- **`services/step_inventory.py`** (nuovo) — `sync_step_component()` e
  `sync_run_step_inventory()`. Tutta la logica di dominio è qui,
  testabile senza HTTP.
- **`services/schema_migrations.py`** (nuovo) —
  `ensure_step_deduction_columns()`, idempotente.
- **`run_setup.start_run()`** — ora ritorna la lista delle deduzioni di
  step (era `None`). I chiamanti che ignorano il ritorno non cambiano.
- **Route** `set_step_actual` e `set_step_lot` — sincronizzano dopo
  ogni modifica. In caso di ammanco: flash + `HX-Refresh`. Nel caso
  normale restano 204 silenziose, per non rubare il focus mentre
  compili più campi di fila.

## Migrazione — OBBLIGATORIA

`ensure-schema` crea le **tabelle** mancanti, mai le **colonne**
(`db.create_all()` non fa ALTER). Quindi su un DB esistente serve
questo passo:

    export FLASK_APP=stoic_eln
    .venv/bin/flask migrate-step-deduction

Equivalente:

    .venv/bin/python scripts/migrate_step_deduction.py

La migrazione è idempotente ed è testata contro un DB con lo schema
vecchio: le righe esistenti sopravvivono con le nuove colonne a NULL,
cioè "nessuna deduzione pregressa" — che è esattamente il significato
giusto per i run già in corso.

**Nota per stoichub (al ritorno dalle ferie)**: la migrazione è un
comando `flask`, quindi vive dentro il package e quindi dentro
l'immagine Docker. Niente più one-liner `python -c`:

    docker compose exec stoic flask migrate-step-deduction

## Test

20 test nuovi in `tests/test_step_inventory_deduction.py`: draft inerte,
recupero delle quantità di bozza ad Avvia, delta in aumento e in
diminuzione, svuotamento, idempotenza, cambio lotto, cambio unità,
clamp con ammanco, componenti senza lotto e voci libere, più quattro
test che passano dalle route HTTP reali e due sulla migrazione contro
schema vecchio.

Suite completa nel sandbox: **711 verdi** (691 + 20; `test_pubchem`
escluso, manca `respx`).

I test sono stati validati per mutazione: sostituendo il delta con
l'importo intero cadono 3 test, togliendo la sync da `start_run()` ne
cadono 6.

## Cosa NON fa questa patch

Niente prelievi multi-fonte, niente solvente recuperato, niente
conteggio riusi: quella è v1.5.0, che si appoggia su queste colonne.
