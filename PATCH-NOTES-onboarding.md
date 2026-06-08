# Stoic ELN — Patch: wizard di configurazione iniziale

Prima voce della **Fase 2 della roadmap v1.0** (adottabilità
server+tablet). Aggiunge un breve wizard a 3 passaggi che appare al
primo accesso di un admin per impostare le scelte chiave del
laboratorio: nome, valuta e codifica delle run.

## Filosofia di design

Il wizard copre **solo** le impostazioni che sono dolorose da
cambiare retroattivamente:

1. **Nome del laboratorio** — appare sui PDF storici, cambiarlo
   introduce incoerenze tra documenti vecchi e nuovi
2. **Valuta** — tutti i costi storici sono numeri salvati in questa
   valuta, cambiarla in seguito NON converte i valori esistenti
3. **Codifica delle run** — cambiare il formato a metà rende
   incompatibili i codici vecchi e nuovi (es. `RX-SUZ-2026-001`
   vs `2026-0001`)

Tutto il resto — utenti, backup, catalogo sostanze, codice prep,
lingua, eccetera — resta nelle Impostazioni regolari, raggiungibile
in qualsiasi momento senza dolore. Niente "tutorial guidato"
generale nel wizard: per quello la Patch B prossima farà la libreria
"Come si fa" con i workflow operativi.

## Comportamento

- Al primo accesso di un admin, se `AppSetting "onboarding.completed_at"`
  è NULL, un hook `before_request` redirect a `/onboarding`.
- L'admin può completare il wizard (i 3 passaggi → conferma) o
  saltarlo. Solo il "Conferma" finale marca il flag come completato.
- Saltando, il wizard riappare al prossimo login admin.
- Sempre raggiungibile via URL diretto `/onboarding` per rilanciare
  manualmente.
- Operatori non-admin: niente redirect (non hanno permesso di
  modificare i settings comunque).
- Richieste HTMX: niente redirect (per non rompere widget Dashboard).
- Endpoint di auth e static: niente redirect (per non rompere logout
  e asset).

## File creati

### Blueprint nuovo

- **`stoic_eln/blueprints/onboarding/__init__.py`** — registrazione
  Blueprint con `url_prefix="/onboarding"`.

- **`stoic_eln/blueprints/onboarding/routes.py`** — 5 route:
  - `GET /onboarding/` — welcome page
  - `GET/POST /onboarding/lab` — step 1 (nome lab → `AppSetting "lab.name"`)
  - `GET/POST /onboarding/currency` — step 2 (valuta → `currency_service.set_currency_code`)
  - `GET/POST /onboarding/run-code` — step 3 (preset → `run_code_service.set_format`)
  - `GET/POST /onboarding/done` — riepilogo + marca completato
  - `GET /onboarding/skip` — bail out senza marcare

  Helper esportati: `is_completed()`, `get_lab_name(default)`.

### Template nuovi

- **`stoic_eln/templates/onboarding/welcome.html`** — benvenuto +
  3 punti del wizard + bottoni "Inizia" / "Salta per ora"
- **`stoic_eln/templates/onboarding/step_lab.html`** — campo text
  nome lab con autofocus
- **`stoic_eln/templates/onboarding/step_currency.html`** — dropdown
  con `currency_service.COMMON_CODES` (EUR, USD, GBP, CHF, JPY, ...)
- **`stoic_eln/templates/onboarding/step_run_code.html`** — 4 preset
  con anteprima del codice generato:
  - Stoic standard: `{op}-{tem}-{year}-{seq:03d}` → `RR-SUZ-2026-001`
  - Anno + sequenza: `{year}-{seq:04d}` → `2026-0001`
  - Anno corto + sequenza: `{yy}{seq:04d}` → `260001`
  - Operatore + sequenza: `{op}-{seq:04d}` → `RR-0001` (scope=operator)
- **`stoic_eln/templates/onboarding/step_done.html`** — riepilogo +
  conferma esplicita

### Tests

- **`tests/test_onboarding.py`** (nuovo), 12 test:
  - Redirect admin se non completato
  - NON-redirect operatore
  - NON-redirect admin se già completato
  - Welcome page render
  - Save nome lab + reject empty
  - Save valuta + reject invalid (es. "INVALID" 7 lettere)
  - Apply preset run code
  - Done step → marca completato + non più redirect
  - Skip → NON marca completato
  - Lab name da AppSetting compare in base template

## File modificati

- **`stoic_eln/__init__.py`** — registrazione blueprint onboarding,
  nuovo `_register_onboarding_redirect()` con `before_request` hook,
  context processor `lab_name` legge prima da `AppSetting "lab.name"`
  con fallback a `app.config["LAB_NAME"]`.

- **`tests/conftest.py`** — pre-popola `AppSetting
  "onboarding.completed_at"` di default così la suite esistente
  (che logga come admin e si aspetta 200) non viene rotta dal
  redirect globale. I test del wizard usano `_clear_completion_flag()`
  per simulare il primo run.

### i18n

- 36 nuove traduzioni EN aggiunte a `messages.po`. `.mo` ricompilati.

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-onboarding-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **570 passed** (558 pre-patch + 12 nuovi).

Niente migration: lo schema non cambia (`AppSetting` esistente già
modella tutto come key-value).

## Verifica visiva

Per provare il wizard nel tuo ambiente:

```
.venv/bin/flask shell
>>> from stoic_eln.models.settings import AppSetting
>>> from stoic_eln.extensions import db
>>> item = db.session.get(AppSetting, "onboarding.completed_at")
>>> if item: db.session.delete(item); db.session.commit()
>>> exit()
```

Poi `make run`, login come admin → dovresti finire automaticamente
su `/onboarding`. Completa il wizard, verifica che le impostazioni
siano applicate nelle Settings, e che al prossimo login NON ricompaia.

## Cosa NON è in questa patch

- **Libreria "Come si fa"** con i workflow operativi (caricare
  sostanza, aggiungere lotto, eseguire run, ...) → Patch B della
  prossima sessione.
- **Tutorial-mode interno** che ti guida step-by-step dentro le
  pagine reali → out of scope.
- **Configurazione backup nel wizard** → resta nelle Settings
  perché è reversibile e non c'è motivo di forzare la scelta al
  primo avvio.
- **Wizard riavviabile con reset esplicito** dalla UI → si rilancia
  via URL diretto `/onboarding` o cancellando il flag dalla shell
  come sopra.
