# Stoic ELN — Patch: card "Template di reazione" nella landing Report

Aggiunge una terza card alla pagina `/reports/` che porta alla
pagina di confronto statistiche per template (già esistente in
`/runs/stats` ma raggiungibile solo da Storico run o dalla detail
di una reazione). Da qui il chimico arriva al confronto template
con un click in meno.

Bonus: fix di una traduzione EN mancante. Nello screenshot
diagnostico si vedeva "Spese" anche in inglese, perché la stringa
non aveva entry nel `messages.po` EN. Aggiunta `Spese → Expenses`.

## File toccati

- **`stoic_eln/templates/reports/index.html`** — aggiunta card
  "Template di reazione" (icona Lucide `bar-chart-3`, link a
  `url_for('runs.stats')`).

- **`stoic_eln/translations/en/LC_MESSAGES/messages.po`** — 3
  nuove entry:
  - `Template di reazione` → `Reaction templates`
  - `Confronto resa, costo e variabilità tra i template di
    reazione: medie, range, deviazione standard.` → relativa EN
  - `Spese` → `Expenses` (fix traduzione mancante)
  - `.mo` ricompilati

- **`tests/test_reports_index.py`** (nuovo) — 2 smoke test:
  - La landing `/reports/` contiene le tre card e i link giusti
  - Il link "Template di reazione" porta a una pagina valida

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-reports-templates-link-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **558 passed** (556 + 2 nuovi).
