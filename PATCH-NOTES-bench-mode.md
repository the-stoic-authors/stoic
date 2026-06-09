# Stoic ELN — Patch: Bench mode (tablet kiosk UX per run execution)

Aggiunge una **modalità banco** a tutta schermo per la pagina di
esecuzione di una run, ottimizzata per uso al laboratorio da
tablet/phone. È la terza voce della Fase 2 della roadmap v1.0
("adottabilità server + tablet").

## Cosa cambia per l'utente

Quando una run è in stato `in_progress`, sulla pagina di dettaglio
appare un bottone **"Modalità banco"** nell'alert "Run in esecuzione".
Cliccandolo:

- Sidebar e header normali spariscono → vista kiosk
- In alto compare una topbar minimale: codice run + bottone "Esci"
- Layout single-column anche su iPad in landscape
- Font del corpo: 17px (era 14)
- Input numerici: 20px, allineati a destra, tabular-nums, ≥48px
- Bottoni: ≥48px (alto) / ≥56px per `.btn-lg` — soddisfa iOS HIG
  44pt minimo per tap target
- Tutti gli input `<input type="number">` hanno `inputmode="decimal"`
  → su iOS/Android Safari/Chrome la tastiera numerica si apre
  direttamente, niente switching dal QWERTY al numerico

Lo stato bench-mode viene salvato in `sessionStorage` con chiave
`stoic.bench.run.<run_id>`, così se ricarichi la pagina (o se chiudi
e riapri la PWA) la modalità resta attiva fino a quando l'operatore
preme "Esci" esplicitamente.

Il bottone bench **NON appare** per run in stato `draft` (setup
ancora in corso, non al banco) né `completed` (record, non più
workflow). Solo `in_progress`.

## Architettura

### CSS overlay non-distruttivo

`static/css/bench.css` definisce solo selettori del tipo
`body.bench-mode .qualcosa`. Quando la classe non c'è, il CSS è
inerte. Nessun cambio strutturale ai template: l'HTML di
`runs/detail.html` resta uguale, il CSS si limita a nascondere
chrome e ridimensionare elementi quando attivato.

### Toggle client-side

`static/js/bench.js` aggiunge/rimuove la classe `bench-mode` al
`<body>` al click di un bottone con `[data-bench-toggle]`. Inietta
anche dinamicamente la topbar minimale. Su `init`, controlla
`sessionStorage` e auto-attiva se ricordato. Localizzazione del
bottone "Esci": Flask espone `window.STOIC_BENCH_EXIT_LABEL` in
base.html (popolato via `_('Esci')`), il JS lo legge da lì.

### Markup hooks nel detail.html

Aggiunte 3 classi/attributi minimali:
- `<button data-bench-toggle data-run-id data-run-code>` nell'alert
  is_running
- `class="step-card"` al `<div class="card">` di ogni step (per CSS
  bench mirato)
- `class="step-component-row"` al `<tr>` dei componenti dello step
- `inputmode="decimal"` su tutti i 4 input `type="number"`

## File creati

- **`stoic_eln/static/css/bench.css`** — 190 righe CSS overlay
- **`stoic_eln/static/js/bench.js`** — 90 righe JS toggle
- **`tests/test_bench_mode.py`** (nuovo, 7 test):
  - bench.css/bench.js serviti con status 200 + MIME corretti
  - base.html linka entrambi e espone `STOIC_BENCH_EXIT_LABEL`
  - run detail mostra il toggle solo per run `in_progress`
    (non per `draft` né `completed`)
  - tutti i `type="number"` hanno `inputmode="decimal"`

## File modificati

- **`stoic_eln/templates/base.html`** — `<link>` per bench.css,
  `<script>` per bench.js, global `STOIC_BENCH_EXIT_LABEL`
- **`stoic_eln/templates/runs/detail.html`** — toggle button (solo
  is_running), classi `step-card`/`step-component-row`,
  `inputmode="decimal"` su tutti i type=number
- **`stoic_eln/translations/en/LC_MESSAGES/messages.{po,mo}`** —
  3 stringhe EN
- **`stoic_eln/translations/it/LC_MESSAGES/messages.{po,mo}`** —
  3 stringhe IT (msgstr = msgid, source language)

### Nuove stringhe i18n

- "Esci" → "Exit"
- "Modalità banco" → "Bench mode"
- "Modalità banco — schermo intero per esecuzione al laboratorio"
  → "Bench mode — fullscreen view for execution at the lab bench"

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-bench-mode-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **594 passed** (587 + 7).

Niente migration. Niente cambi al modello dati.

## Verifica visiva

1. **Avvia una run** (oppure aprine una già `in_progress`)
2. Nella pagina detail, nell'alert blu "Run in esecuzione", vedi un
   bottone **"Modalità banco"** in alto a destra
3. Click → sidebar e header spariscono, compare topbar minimale in
   alto con codice run + "✕ Esci"
4. Tutti gli input numerici (peso, quantità) hanno tastiera numerica
   diretta su iPad/iPhone
5. Tap target più grandi, font più grande, layout in colonna unica
6. Click su "✕ Esci" → torni alla vista normale
7. Reload pagina (o chiudi+riapri PWA) durante bench-mode → la
   modalità si riattiva da sola
8. Apri una run `draft` (in setup) → il bottone NON c'è
9. Apri una run `completed` → il bottone NON c'è

## Cosa NON è in questa patch

- **Auto-save inline degli input** — al momento ogni input ha il
  suo bottone "Aggiorna" come prima; in bench mode il bottone è
  più grosso, ma non viene scatenato al blur. Aggiungere auto-save
  inline (con feedback visivo) può venire in una patch successiva
  se l'esperienza utente lo richiede.
- **Layout step accordion / corrente espanso** — per ora gli step
  restano tutti aperti come prima. Collassare automaticamente quelli
  fatti e quelli futuri richiederebbe più lavoro di JS interattivo;
  non strettamente necessario per il caso d'uso v1.
- **Modifica della pagina di setup run** — bench mode è solo per
  esecuzione (`in_progress`). Setup resta come è (meno usato al
  banco).
- **Sticky controls** — niente sticky button "Concludi run" in
  fondo. Lo scroll è considerato accettabile.
