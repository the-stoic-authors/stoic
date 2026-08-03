# Patch — Production cost report (per substance, per batch)

A new report (`Reports → Production costs`) showing what it cost to **make**
each in-house batch, aggregated per substance, with the **cumulative** and
**direct** cost bases side by side.

> Apply this **after** P3 (it shares `messages.po` with P3; this tarball's
> catalog is the superset). No schema changes — pure read/aggregation over
> existing data, so **no migration**.

---

## What it shows

For each produced batch (an `InventoryItem` with `source_run_id` — created by
`complete_run`), the production cost is the cost of the materials its run
consumed, which `run_cost.compute_run_cost` already computes on two bases:

* **Cumulative** — every material consumed, including the embedded cost of
  self-made intermediates used in the run (full cost accounting).
* **Direct** — fresh purchased money only, excluding intermediates already
  paid for in earlier runs (cash cost).

When a run yields several products, its cost is split across the product
batches **in proportion to mass** (the same allocation `complete_run` uses),
so €/g is uniform across a run's products.

The report has two levels over a selectable period:
* **per substance** — batch count, total mass produced, total production cost
  (cumulative + direct), and weighted-average €/g on both bases;
* **per batch** — batch code, source run (linked), production date, mass,
  cost and €/g on both bases. Runs with unpriced components are flagged
  *partial* (their costs are understated, not wrong).

---

## Files
- `services/production_cost_report.py` (new) — `compute_production_cost_report`.
- `blueprints/reports/routes.py` — `/reports/production` route.
- `templates/reports/production.html` (new) + a card on `reports/index.html`.
- EN catalog updated for the new strings.
- `tests/test_production_cost_report.py` (new): cumulative vs direct
  (11 € / 5 € → 5.5 / 2.5 €/g), multi-product mass split (uniform €/g, cost by
  mass), and the page renders.

No models, no schema, no migration.

---

## Apply

```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-production-cost-report.tar.gz -C ~/Projects/
make translations
make run
```

Then open `Reports → Production costs`. Numbers appear once you have completed
runs that produced batches (and priced lots for the consumed materials).

Full suite: **634 passed**, 16 skipped — the 9 sandbox failures are the usual
RDKit-only ones, not regressions.
