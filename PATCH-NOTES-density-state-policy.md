# Stoic ELN — Patch: stato fisico per la politica unità inventario (v2)

Affinamento della politica unità g/mL introdotta dalla patch
precedente. Una **densità nota** non è più sufficiente, da sola, a
considerare una sostanza dosabile in volume — serve anche che la
sostanza sia liquida alla temperatura di lavoro.

## Cosa cambia rispetto alla v1 di questa patch

Due fix di qualità rispetto al primo tentativo:

1. **Regola chimica più stretta**: il flag `is_solvent=True` NON
   bypassa più il controllo dello stato fisico. Un solvente è per
   definizione liquido alla temperatura d'uso; se ha MP sopra
   temperatura ambiente non è un solvente, è al massimo un melt.
   `is_solvent + MP alto` ora ricade nel ramo "solvent_no_density"
   (solo mL, ma senza sync via densità). Cambio di una sola riga
   nel servizio e del test corrispondente.

2. **Import fix nei test del cleanup**: i due test che esercitano
   `scripts/cleanup_mL_on_solid_substances.py` usavano
   `from scripts.cleanup_mL_on_solid_substances import main`. Sul
   Mac fallivano con `ModuleNotFoundError: No module named 'scripts'`
   perché `scripts/` intenzionalmente non è un package Python (niente
   `__init__.py`: sono utility standalone). Riscritti per usare
   `importlib.util.spec_from_file_location()`, che carica il modulo
   da path senza dipendere da come pytest/Python configura il
   namespace package discovery.

## Bug osservato

Durante il collaudo della patch precedente è emerso che lo script
di migration aveva propagato i mL su 7 lotti, **tra cui anche
substance come il sodio solfato anidro** (Na₂SO₄, densità 2.66
g/cm³, MP 884°C). PubChem fornisce densità del solido cristallino
per molti sali, e questi valori finivano nel catalogo Stoic durante
i fetch automatici. La densità è formalmente corretta ma chimicamente
irrilevante: nessuno mette il sodio solfato in una siringa.

Risultato: il magazzino mostrava lotti di sali "dosabili in mL" che
non lo sono.

## Regola nuova

Una sostanza è dosabile in volume (sincronizzato g/mL via densità)
se **tutte** le seguenti sono vere:

1. Ha una `density` nota e positiva.
2. Non risulta "solid" al controllo `detect_state()` (che usa la
   soglia di 25°C su `melting_point_c` come stato a temperatura
   ambiente).

Il flag `is_solvent=True` non bypassa il controllo MP: chimicamente
un solvente è un liquido alla temperatura d'uso, una sostanza con
MP alto non lo è.

### Tabella delle decisioni

| Caso | Densità | MP | is_solvent | Politica |
|------|---------|----|----|----------|
| Sodio solfato | 2.66 | 884°C | False | solo g (densità ignorata) |
| Hexanoyl chloride | 0.976 | -90°C | False | g+mL sync |
| Sostanza con densità ma senza MP nel catalogo | settata | NULL | False | g+mL sync (densità assunta intenzionale) |
| Naftalene mis-flaggato come solvente | 1.0 | 80°C | True | solo mL (sync downgrade per MP alto) |
| NaCl | NULL | 800°C | False | solo g |
| Solvente legittimo senza densità | NULL | qualsiasi | True | solo mL |

## File toccati

### Service

- **`stoic_eln/services/inventory_quantity.py`** —
  `policy_for_substance()` ora chiama `substance.detect_state()`.
  Se ritorna `"solid"`, la densità viene **downgrade a None** ai
  fini del calcolo della politica, indipendentemente dal flag
  `is_solvent`.

### Cleanup script

- **`scripts/cleanup_mL_on_solid_substances.py`** (nuovo) — Da
  lanciare **una volta sola** dopo l'applicazione della patch.
  Percorre tutti gli active `InventoryItem`, ri-valuta la
  politica sotto le nuove regole, e per i lotti che ora risultano
  "solo g" ma hanno ancora un `quantity_mL` propagato dalla
  migration precedente:
  - se `quantity_g` è popolato → svuota `quantity_mL` (e
    `initial_quantity_mL`)
  - se solo `quantity_mL` è popolato (caso raro) → calcola g da
    mL via densità del catalogo, poi svuota mL
  Idempotente: re-lanciabile in sicurezza.

### Tests

- **`tests/test_inventory_quantity_policy.py`** — aggiunti 7 test:
  - 5 sul nuovo controllo stato:
    - Sostanza solida con densità (Na₂SO₄) → trattata come no_density
    - Solvente mis-flaggato con MP alto → solvent_no_density (mL ma
      senza sync)
    - Liquido normale (HexCl) → resta synced
    - Densità senza MP → assunta intenzionale
    - MP esattamente a 25°C → detect_state ritorna "liquid", synced
  - 2 sul cleanup script: corregge solidi, non tocca liquidi, è
    idempotente. Usano `importlib.util` per caricare lo script,
    indipendente dalla configurazione package discovery di Python.

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-density-state-policy-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **556 passed** (549 pre-patch + 7 nuovi).

### Cleanup dei dati esistenti

I 7 lotti che la migration precedente ha fixato possono includere
sostanze che ora la nuova regola classifica come solide. Per
ripulirli:

```
cd ~/Projects/stoic-eln
.venv/bin/python -m scripts.cleanup_mL_on_solid_substances
```

Lo script stampa un sommario con i lotti modificati.

## Cosa NON è in questa patch

- **Soglia configurabile per la classificazione solid/liquid**: il
  valore 25°C è ereditato da `detect_state()` che è la fonte di
  verità preesistente nel modello.
- **Cancellare la densità sbagliata dalla scheda della sostanza**:
  per Na₂SO₄ la densità 2.66 è formalmente corretta e potrebbe
  servire ad altri usi. La lasciamo nel catalogo; semplicemente
  la ignoriamo a fini di dosaggio.
