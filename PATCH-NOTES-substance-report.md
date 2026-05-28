# Stoic ELN — Patch: Report per Substance

Aggiunge un report per singola sostanza con tre viste, su un periodo
selezionabile. Quarta voce della Fase 1 della roadmap v1.0.

## Le tre viste

1. **Consumo** — quanto della sostanza è stato consumato nel periodo,
   diviso per fonte (reazioni, step di reazione, preparazioni) e per
   unità (g e mL, mai convertiti via densità — un consumo "125 g +
   40 mL" si mostra così).

2. **Copertura di stock** (il "turnover") — consumo medio giornaliero
   nel periodo, stock attuale, e stima "ai ritmi attuali lo stock
   dura ~N giorni". Scelta di design: NON usiamo "giorni da acquisto
   a esaurimento" perché `InventoryItem` non ha un timestamp di
   esaurimento; il daily-rate + copertura usa dati che abbiamo davvero
   (eventi di consumo datati). Disclaimer in UI che la stima è
   indicativa.

3. **Andamento prezzi** — prezzo unitario (€/g o €/mL) di ogni lotto
   nel tempo, sparkline SVG pure-Python, più una tabella per fornitore
   (medio / min / max). Ogni lotto è un punto-prezzo reale alla sua
   data di acquisto.

## Decisioni di design

- **Consumo da 3 fonti**: RunComponent (componenti principali), 
  RunStepComponent (componenti negli step), MixturePrepConsumption
  (precursori consumati nelle preparazioni). Solo run con status
  `completed` e `completed_at` nel periodo contano.
- **Due totali separati per unità** (g e mL), mai conversione via
  densità.
- **Copertura via daily-rate**, non via timestamp di esaurimento
  (assente nel modello).
- **Prezzo dai lotti** `InventoryItem` (ogni lotto = punto-prezzo a
  `purchased_at`), non dagli ordini.
- **Periodo selezionabile**: preset 3m / 6m / 12m + range custom,
  default 12 mesi.

## File toccati

### Service (nuovo)

- **`stoic_eln/services/substance_report.py`** — `compute_substance_report(substance_id, date_from, date_to)`
  ritorna un `SubstanceReport` con le tre viste. Helper privati per
  ciascuna fonte di consumo, per lo stock corrente, per il cost trend.
  `render_cost_sparkline_svg()` per il grafico (stile gemello di
  `template_stats.render_sparkline_svg`).

### Routes

- **`stoic_eln/blueprints/reports/routes.py`** — Nuova route
  `/reports/substance` (picker) e `/reports/substance/<id>` (report).
  Helper `_resolve_period()` per i preset/custom.

### Templates

- **`stoic_eln/templates/reports/substance.html`** (nuovo) — Picker
  sostanza + selettore periodo + le tre viste (consumo, copertura,
  prezzi) con grafico SVG e tabelle.
- **`stoic_eln/templates/reports/index.html`** — Aggiunta card
  "Sostanza" nella landing dei report.
- **`stoic_eln/templates/substances/detail.html`** — Aggiunto bottone
  "Report" nell'header, link a `/reports/substance/<id>`.

### i18n

- **`messages.po` EN** — 39 nuove entry per le stringhe IT del report.
- **`.mo`** ricompilati.

### Tests

- **`tests/test_substance_report.py`** — 13 test:
  - Consumo: somma runs+steps, esclude run fuori finestra, esclude
    run non-completed
  - Copertura: daily-rate + stock + copertura, "dati insufficienti"
    senza consumo
  - Cost trend: punti + per-supplier, esclusione lotti fuori finestra
  - SVG: render con 2+ punti, vuoto con 1 punto
  - Substance inesistente → None
  - Route smoke: picker senza id, report con id, id sconosciuto

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-substance-report-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: 518 passed (505 pre-patch + 13 nuovi). Niente migration:
solo servizio, route, template, test, traduzioni.

## Cosa NON è in questa patch

- **Export PDF del report** — out of scope per ora.
- **Report aggregato multi-sostanza** — questo è per singola sostanza;
  un confronto cross-substance è una possibile evoluzione.
- **Consumo in mmol** — riportiamo g e mL (le unità misurate); la
  conversione a moli richiederebbe MW sempre noto e introdurrebbe la
  stessa ambiguità che evitiamo nel non-convertire g↔mL.
