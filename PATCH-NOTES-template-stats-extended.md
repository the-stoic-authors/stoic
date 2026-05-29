# Stoic ELN — Patch: Template stats estese (€/mol + deviazione standard)

Quinta e ultima voce della **Fase 1 della roadmap v1.0**. Completa
quello che la roadmap chiama "Reports per Reaction template": yield
medio, costo per mole, deviazione standard.

## Stato prima della patch

`template_stats.py` calcolava già aggregati per template (gruppi per
`template_code_base`, così SUZ.1 e SUZ.2 stanno insieme):
- Yield medio
- Costo medio/min/max in €
- €/g di prodotto medio/min/max
- Sparkline SVG (yield%, cost €, cost €/g)
- Pagine `/reactions/<id>/stats` e `/runs/stats`

`run_cost.py` calcolava già `cost_per_mol_product()` su singolo run
via `product_unit_metrics()`.

## Cosa aggiunge questa patch

A livello di **aggregato per template**:
- **€/mole di prodotto** medio / min / max (riusando il calcolo già
  esistente su singolo run, aggregato sui run del template)
- **Deviazione standard** su yield_percent, cost_eur, cost_per_g,
  cost_per_mol

A livello di **UI**:
- Pagina `/reactions/<id>/stats`: nuova card €/mol, σ accanto a ogni
  aggregato, nuova sparkline €/mol nel grafico, nuova colonna €/mol
  nella tabella per-run
- Pagina `/runs/stats`: nuova colonna €/mol medio, σ sotto ogni
  aggregato in tabella confronto template

## Decisioni di design

- **Deviazione standard del campione** (`statistics.stdev`, ddof=1),
  non della popolazione. Giustificazione: i run eseguiti sono un
  campione finito della procedura, non l'intera popolazione possibile.
- **`None` per n < 2 run**, non 0. Un singolo run non ha spread da
  misurare; mostrare 0 sarebbe fuorviante. La UI rende "—" in quel
  caso.
- **σ nascosto in UI quando = 0** (run identici → stddev 0, non
  serve mostrarlo come "σ €0.00", è rumore visivo).
- **€/mol calcolato su singolo run prima di aggregare**, NON
  aggregato dei dati grezzi. Aggregare medie di medie distorce — qui
  prendiamo i €/mol per-run (già calcolati da `product_unit_metrics`)
  e poi facciamo avg/min/max/stddev su quella lista.
- **Run senza MW del prodotto contribuiscono a cost_eur ma non a
  cost_per_mol**: il singolo run ha `cost_per_mol=None`, e
  l'aggregato semplicemente esclude i None (stesso pattern già usato
  per cost_per_g).

## File toccati

### Service

- **`stoic_eln/services/template_stats.py`**:
  - `import statistics`
  - `RunPoint`: nuovo campo `cost_per_mol: float | None`
  - `TemplateStats`: nuovi campi `avg/min/max/stddev_cost_per_mol`,
    `stddev_yield_percent`, `stddev_cost_eur`, `stddev_cost_per_g`
  - `_build_run_point`: popola `cost_per_mol` da
    `product_unit_metrics.per_mol`
  - `stats_for_template`: helper `_stddev()` (sample, None se n<2),
    aggrega i nuovi metric
  - `render_sparkline_svg`: nuovo metric `"cost_per_mol"`

### Routes

- **`stoic_eln/blueprints/reactions/routes.py`** (stats endpoint):
  passa al template anche `sparkline_cost_per_mol` (color #6f42c1).

### Templates

- **`stoic_eln/templates/reactions/stats.html`**:
  - Cards KPI: aggiunta card "€/mol medio", σ sotto ogni metrica
  - Sparklines: aggiunta sparkline €/mol
  - Tabella per-run: aggiunta colonna €/mol
- **`stoic_eln/templates/runs/stats.html`**:
  - Tabella confronto: aggiunta colonna €/mol, σ sotto ogni
    aggregato (nascosto se σ=0)

### Tests

- **`tests/test_template_stats_extended.py`** (nuovo), 9 test:
  - `cost_per_mol`: aggregati avg/min/max corretti, None quando
    no runs, run senza MW del prodotto correttamente esclusi
    dall'aggregato
  - `stddev`: 2 run con yield 40/60 → σ=14.14, single run → None,
    run identici → 0, stddev_cost_eur e stddev_cost_per_g coerenti
  - `sparkline`: render con metric="cost_per_mol", metric ignota
    ritorna stringa vuota

### i18n

Nessuna nuova traduzione necessaria — le stringhe nuove ("per run",
"medio per run", "del prodotto (cumulativo)") erano tutte già nel
`.po` EN. `σ` è simbolo Unicode, indipendente dalla lingua.

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-template-stats-extended-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **527 passed** (518 pre-patch + 9 nuovi). Niente migration.

## Cosa NON è in questa patch

- **Export PDF/Excel del report template** — out of scope per ora.
- **Filtri temporali sul report template** — il report attuale
  aggrega tutti i run mai eseguiti del template. Un selettore di
  periodo come quello del Report per Substance sarebbe una possibile
  evoluzione.
- **Confronto a coppie tra template** — la tabella di `/runs/stats`
  mostra tutti i template in una singola tabella, sufficiente per ora.
