# Script — Backfill production cost on existing mixture lots

Companion to the prep-costing fix: that fix prices **new** mixture lots; this
script prices the ones prepared **before** it (which still have
`total_cost_eur = None`), so they start counting in run costs too.

## What it does
For every mixture lot with no cost that came from a recorded `MixturePrep`, it
recomputes the cost from that prep's consumptions — the sum of the **priced**
precursor lines (`MixturePrepConsumption.imputed_cost_eur`, the same per-line
cost the app uses). An unpriced precursor is skipped; the cost is set as long as
at least one precursor was priced.

Chained preps (a mixture made from another mixture) are handled by repeating
passes until nothing more can be priced — so once HCl 12N is priced, the HCl 6N
made from it gets priced on the next pass, and so on.

Lots with no prep (manually-added "quick label" lots) are left alone — there's
no consumption data to price them from.

## Use
```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-mixture-cost-backfill.tar.gz -C ~/Projects/

.venv/bin/python scripts/backfill_mixture_costs.py            # PREVIEW (dry-run)
.venv/bin/python scripts/backfill_mixture_costs.py --apply    # write
```

It's **dry-run by default**: the preview prints exactly which lots would be
priced (and to what, flagging partial ones) without writing anything. Re-run
with `--apply` once the preview looks right. Safe to re-run — only lots that
still have no cost are touched.

Example preview:
```
Mixture lots without a cost: 7
  priced now : 5
    HCL6N-2026-003: 41.00 EUR
    PE-ETOAC-52-2026-001: 3.20 EUR  (partial: 1/2 priced)
    ...
  no prep    : 1  (manually-added lots, skipped)
  no price   : 1  (no priced precursor)
```

## Files
- `scripts/backfill_mixture_costs.py`
- `tests/test_backfill_mixture_costs.py` — legacy lot gets priced, dry-run
  writes nothing, and the chained mixture-from-mixture case prices both lots
  across passes (lot6 = 41 €, lot3 = 21.5 € derived from it).

No schema, no migration. Apply the prep-costing fix first (or together); the
backfill reuses the model's existing per-line cost so it works either way.
