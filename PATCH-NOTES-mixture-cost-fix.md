# Fix — Prepared mixtures now carry a production cost

## The gap
A prepared mixture is stored as an inventory lot (`InventoryItem.mixture_id`),
created by `execute_preparation`. That lot was created **without a cost**
(`total_cost_eur = None`), so:

- the mixture lot had no `cost_per_unit`;
- a run that consumed the mixture (eluent, workup buffer) found no price →
  the line was flagged **incomplete** and contributed **€0** to the run cost.

So mixtures were invisible to the synthesis cost.

## The fix
At preparation time, the output mixture lot is now priced from the precursors
actually consumed — exactly as `complete_run` prices a product batch:

```
output_lot.total_cost_eur = Σ (consumed quantity × precursor lot €/unit)
```

over the **priced** precursor lots (reusing `run_cost._line_cost` for the
g vs mL unit matching). Per your call: an unpriced precursor is **skipped**;
the total is set as long as at least one precursor was priced (partial costs
are useful). If no precursor is priced, the lot cost stays `None`.

This **chains automatically**: once HCl 12N lots are priced, HCl 6N prepared
from them inherits the cost; and any run consuming the mixture now counts it
(no change to `run_cost` was needed — it already reads the lot's `cost_per_unit`
whether the lot is a substance or a mixture).

A mixture lot has no `source_run_id`, so its cost counts as **direct** money in
a run — correct for the common case (mixtures made from purchased chemicals).

## Files
- `stoic_eln/services/prep_service.py` (price the output lot in
  `execute_preparation`).
- `tests/test_prep_service.py` (+3): full cost (41 €), partial when a precursor
  is unpriced (40 €), and `None` when none are priced.

No schema, no migration. Independent of the v1-prep bundle — applies on top of
it cleanly.

## Apply
```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-mixture-cost-fix.tar.gz -C ~/Projects/
make run
```

## Note — existing mixture lots
Lots prepared **before** this fix still have no cost; they'll be priced the next
time you prepare that mixture. If you want, I can add a one-off backfill script
that recomputes cost for existing mixture lots from their recorded
`MixturePrep` consumptions.

Full suite: **643 passed**, 16 skipped (9 sandbox RDKit-only failures).
