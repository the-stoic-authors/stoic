# Stoic ELN — P2: Componenti "voce libera" + calcolo Ø colonna

Seconda della serie procedure standard. Introduce il primitivo
generale concordato: componenti di step FUORI INVENTARIO con unità
di misura libera, più il primo ratio_kind calcolato.

## Voci libere

ReactionStepComponent / StepTemplateComponent / RunStepComponent
guadagnano `free_name` + `free_unit`. Lo XOR diventa a 3 vie:
sostanza ⊻ miscela ⊻ voce libera (CHECK aggiornato nel DB). UI:
terzo radio "Voce libera" nel form componenti dello step (nome +
unità testo libero). Le voci libere attraversano la libreria P1 e
lo snapshot Run.

## Nuovi ratio_kind

- `fixed_value` — valore fisso nell'unità libera ("Celite 5 g",
  "Colonna Ø 30 mm" hardcoded)
- `column_diameter_mm` — CALCOLATO: ratio_value = altezza letto
  in cm (decisa per-procedura, come concordato); il diametro
  deriva dalla massa del componente con ruolo "fase stazionaria"
  (nuovo role `stationary_phase`) nello stesso step:
  d_mm = 10·2·√((m/ρ)/(π·h)), ρ silice bulk = 0.5 g/mL (costante
  documentata in step_calc). Verificato: 30 g/15 cm → 22.6 mm;
  scala 4× → Ø 2×.

Al Run il valore appare come "suggerito: 23 mm" sotto la voce —
arrotondi tu alla colonna che possiedi.

## Migrazione OBBLIGATORIA (CHECK constraint → rebuild tabelle)

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-p2-free-components.tar.gz -C ~/Projects/
.venv/bin/python scripts/migrate_p2_free_components.py
make translations
make test 2>&1 | tail -3
```

Atteso: **642 passed** (635 + 7). La migrazione è idempotente e
testata empiricamente su DB vecchio-schema (dati preservati, riga
free accettata, riga tutta-NULL rifiutata).

## File

Mod: reaction_step_component.py, step_template.py, run_step.py
(free fields), reaction_component.py (role stationary_phase),
models/__init__ (__all__ fix), step_calc.py (StepQuantity.free,
compute_column_diameter_mm, run-level resolution), run_setup.py
(snapshot), reactions/routes.py (XOR 3 vie), procedures/routes.py
(copie), __init__.py (_step_quantity esteso), _step_card.html
(form+righe+kind select), runs/detail.html (rendering), .po EN.
Nuovi: scripts/migrate_p2_free_components.py,
tests/test_free_step_components.py (7 test).

## Prossima: P2b — seed procedure standard

Flash facile/media/difficile (Still 30/50/100 g/g + Ø colonna 15 cm
+ eluente), estrazione standard, caricate al primo avvio e
modificabili. Poi P3.
