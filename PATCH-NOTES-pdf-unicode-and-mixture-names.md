# Stoic ELN — Patch: nomi miscele nested + caratteri Unicode nei PDF

Due bug emersi insieme nel collaudo dell'iPad, fixati nella stessa
patch perché entrambi tipi "rendering" e di basso impatto sul codice.

## Bug 1 — Nome mixture-componente mancante

Quando una mixture o una run ha tra i suoi componenti **un'altra
mixture** (es. "HCl 6N" la cui ricetta usa "HCl 12N" come precursore,
o una run dove HCl 12N viene usata nel workup), il nome del
componente non compariva. Si vedeva:

  - Nella lista `/mixtures/`: "**, Water**" sotto Components
  - Nei PDF di run, **in 3 punti distinti**:
    * Sezione 1 "Componenti" (tabella main components della run)
    * Sezione 4.x (tabella di ogni step, es. workup)
    * Sezione 5 "Costo materiali" (tabella aggregata via run_cost)

### Causa

Quattro punti del codice usavano `c.substance.name` (o variante con
fallback a `"?"`) senza gestire il caso in cui il componente sia una
mixture-nested (`child_mixture_id is not None`, `substance_id is None`).

I modelli (`MixtureComponent`, `RunComponent`, `RunStepComponent`)
già avevano una proprietà `display_name` che ritorna il
`mixture.display_label` quando il componente è mixture-backed,
o il `substance.name` quando è substance-backed. Era solo da usare.

### Fix

Sostituzione di tutte le occorrenze di `sub.name if sub else "?"`
con `c.display_name` (o `sc.display_name`). Quattro punti coperti:

  - `templates/mixtures/_list_table.html` — lista mixture
  - `services/run_cost.py` — main + step components (2 punti) per
    il PDF sezione 5
  - `services/pdf_run.py` — main components nella sezione 1
  - `services/pdf_run.py` — step components nella sezione 4.x

Pulizia minore in `run_cost.py`: rimosse 2 variabili `sub = c.substance`
ora inutilizzate.

**Nota**: `templates/mixtures/detail.html` era già giusto — quella
pagina gestiva esplicitamente il branch `{% if c.child_mixture %}
... {% elif c.substance %}`.

## Bug 2 — Caratteri quadrati neri nei PDF

I PDF mostravano "**Na■SO■**" invece di "Na₂SO₄", e in generale ogni
pedice / apice / lettera greca finiva come tofu (quadrato nero).

### Causa

ReportLab usava i font built-in `Times-Roman`, `Times-Bold`,
`Times-Italic`, `Times-BoldItalic`. Questi sono i "14 standard PDF
fonts" — supportano solo **Latin-1** (codepoints ≤ U+00FF).

Per chimica questo è inaccettabile: Na₂SO₄, NaHCO₃, α-pinene, β-naphthol
nei campi note e procedure, formule PubChem importate con pedici.
ReportLab quando non trova un glyph disegna un quadrato.

### Fix

Bundle di **DejaVu Serif** (4 variants: regular, bold, italic,
bold-italic), registrato in ReportLab e usato al posto di Times-Roman
in tutti i PDF generator. DejaVu copre pedici, apici, Greco,
Latin esteso. Bundle nel repo (~1.4 MB totali) anziché dipendere da
font di sistema, così il PDF è deterministico tra Mac, server Linux
e Pi 4.

## File creati

  - **`stoic_eln/services/pdf_fonts.py`** — modulo che registra
    DejaVu Serif una sola volta (idempotente) ed esporta i nomi
    `FONT_REGULAR`, `FONT_BOLD`, `FONT_ITALIC`, `FONT_BOLD_ITALIC`
  - **`stoic_eln/static/fonts/DejaVuSerif{,-Bold,-Italic,-BoldItalic}.ttf`**
  - **`stoic_eln/static/fonts/LICENSE.md`** — note sulla licenza DejaVu

## File modificati

  - **`services/pdf_run.py`** — import + register + sostituzione
    `"Times-Bold"` → `FONT_BOLD` (etc.) in 15 punti + fix bug 1 in
    2 tabelle (main components, step components)
  - **`services/pdf_audit.py`** — analoga sostituzione font, 5 punti
  - **`services/run_cost.py`** — fix bug 1 (display_name in 2 punti)
    + rimozione variabili inutilizzate
  - **`templates/mixtures/_list_table.html`** — fix bug 1

## Tests

- **`tests/test_pdf_unicode_and_mixture_names.py`** (nuovo), 5 test:
  - `register()` è idempotente
  - Il font registrato ha i glyph per subscripts, superscripts e
    Greco
  - Render PDF con stringa contenente Na₂SO₄ + α-pinene non causa
    errori ReportLab
  - `MixtureComponent.display_name` per child-mixture ritorna il
    label della mixture nested
  - `/mixtures/` smoke test: nested mixture mostra il nome

Un test end-to-end del PDF con step-component mixture-backed era
stato considerato ma scartato: richiede un setup substanziale
(Run + RunStep + RunStepComponent con tutti i NOT NULL constraint),
e la copertura unitaria su `display_name` è già garantita. La
verifica resta visiva (riapri un PDF dopo aver applicato la patch).

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-pdf-unicode-and-mixture-names-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **587 passed** (582 + 5).

## Verifica visiva

1. Vai a `/mixtures/`: la riga "HCl 6N" deve mostrare "HCl 12N, Water"
   nella colonna Components (prima ", Water").
2. Apri il PDF di una run con uno step (es. workup) che usa una
   mixture come componente:
   - Sezione "4.x — Workup" → la riga della mixture deve mostrare
     il suo nome (prima "?")
   - Sezione "5. Costo materiali" → idem
3. Apri qualunque PDF con testo contenente formule chimiche con
   pedici (es. Na₂SO₄, H₂O, CO₂) → i pedici sono renderizzati
   correttamente, non più quadrati neri.

## Cosa NON è in questa patch

- Test PDF end-to-end con mixture-backed step component (richiede
  costruzione completa di Run/Step a mano).
- Migrazione del font su Helvetica/altri stili — DejaVu Serif copre
  il caso d'uso.
- Embedding sub-set manuale — ReportLab fa già subset embedding nei
  PDF generati.
