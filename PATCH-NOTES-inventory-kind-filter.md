# Stoic ELN — Patch: filtro "Tipo" in inventario

Aggiunge un filtro **Tipo** al magazzino (`/inventory/`) con 4 valori:

- **Tutti** (default, nessun filtro)
- **Sostanze** — solo lotti di Substance
- **Miscele** — solo lotti di Mixture
- **Solventi** — sottoinsieme stretto di Sostanze dove
  `substance.is_solvent=True`. Le miscele sono escluse (non hanno un
  flag `is_solvent` equivalente nel loro modello)

Il filtro `is_solvent` esisteva già sul modello `Substance` (campo
Boolean accanto a `density` e `state`), usato dall'UI di creazione
sostanza per attivare il dosaggio in mL invece che in g. Questa patch
lo espone come dimensione di filtro nella vista magazzino.

## File toccati

- **`stoic_eln/blueprints/inventory/routes.py`** — Aggiunto parsing
  del parametro `?kind=`, validazione (`all|substance|mixture|solvent`,
  fallback a `all` per valori sconosciuti), filtro nella query, passato
  ai template sia HTMX che pagina piena.
- **`stoic_eln/templates/inventory/list.html`** — Aggiunto dropdown
  "Tipo" come 2° filtro (dopo "Cerca"). Layout ridistribuito:
  `q→3, kind→2, status→2, supplier→2, group→2, button→1` = 12 colonne.
  Bottone "Filtra" → solo icona per recuperare spazio.
- **`stoic_eln/translations/en/LC_MESSAGES/messages.po`** — 1 nuova
  entry: `"Solventi" → "Solvents"`. Le altre 3 stringhe ("Tipo",
  "Sostanze", "Miscele") erano già nel `.po` da patch precedenti.
- **`tests/test_inventory_kind_filter.py`** — Nuova suite, 6 test:
  - `kind=all` mostra tutti i 4 lotti del fixture (substance,
    solvent substance, 2 mixtures)
  - `kind=substance` esclude le miscele ma include i solventi
  - `kind=mixture` mostra solo le miscele
  - `kind=solvent` mostra solo le substance con `is_solvent=True`,
    escludendo sia substance non-solventi che mixture
  - valori invalidi (`kind=banana`) ricadono su `all`
  - composizione con altri filtri (`?kind=mixture&q=HCL`) funziona

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-inventory-kind-filter-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: 496 passed (490 pre-patch + 6 nuovi). Niente migration da
lanciare (nessuna modifica al modello).
