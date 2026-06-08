# Stoic ELN — Patch: Progressive Web App (manifest + iOS support)

Aggiunge supporto PWA così Stoic può essere installato come app
sulla home screen di iPad/iPhone (e Android), aperto a tutto
schermo senza barre del browser, con la sua icona e il suo nome
nello switcher delle app.

Seconda voce della Fase 2 della roadmap v1.0 ("adottabilità server
+ tablet").

## Cosa cambia per l'utente

Aprendo Stoic da Safari su iPad/iPhone, dal menu di condivisione
diventa disponibile "**Aggiungi alla schermata Home**". Tap →
appare un'icona di Stoic identica a quella di un'app nativa. Al
tap apre Stoic a tutto schermo, senza la barra dell'URL, con
splash screen del brand color, e compare nello switcher delle app
come app a sé stante.

Stessa cosa su Android Chrome: "Installa app" appare nel menu.

Il nome sull'icona riflette il **nome del laboratorio** configurato
dal wizard di onboarding (o "Stoic" come fallback).

**Cosa NON fa questa patch**: niente offline support, niente
Service Worker, niente sync in background. Sono tutti possibili
in seguito, ma non sono necessari per il "feel da app installata".

## Architettura

### Manifest dinamico

`GET /manifest.webmanifest` restituisce JSON con MIME
`application/manifest+json`. Il `name` viene popolato dal
`get_lab_name()` della patch onboarding, così l'install riflette
le scelte del wizard. Tutti gli altri campi sono statici.

### Icone

Generate dal logo SVG fornito dall'utente
(`stoicsqb.svg` → `static/img/pwa/icon-source.svg`) via cairosvg in:

  - `icon-192.png` — minimo per PWA installer (Android e desktop)
  - `icon-512.png` — alta risoluzione per splash e contesti grandi
  - `icon-180.png` — apple-touch-icon (iOS ignora il manifest per
    l'icona, usa il `<link rel="apple-touch-icon">`)
  - `icon-maskable-512.png` — variant con `purpose: maskable` per
    Android adaptive icons (crop circolare/rounded automatico)

Il SVG sorgente resta in repo come fonte di verità — possiamo
rigenerare le PNG in qualsiasi momento se cambia il logo.

### Tag nel `<head>`

`base.html` aggiunge:

```html
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" sizes="180x180" href="/static/img/pwa/icon-180.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{{ lab_name }}">
<meta name="theme-color" content="#1F3864">
<meta name="mobile-web-app-capable" content="yes">
```

Il `theme_color` (#1F3864) è il colore brand di Stoic preso dalle
variabili CSS esistenti (`--stoic-primary`).

## File creati

- **`stoic_eln/static/img/pwa/icon-source.svg`** — logo originale
- **`stoic_eln/static/img/pwa/icon-{192,512,180,maskable-512}.png`**
  — icone generate
- **`tests/test_pwa.py`** (nuovo), 11 test:
  - Manifest endpoint: status 200, MIME corretto, campi richiesti,
    dimensioni icona obbligatorie, maskable presente, lab_name
    propagato, short_name fallback per nomi lunghi
  - Base template: `rel="manifest"` presente, `apple-touch-icon`,
    4 meta tag iOS, `apple-mobile-web-app-title` riflette lab_name
  - Static assets: tutti i 4 PNG servono 200 con MIME image/png

## File modificati

- **`stoic_eln/blueprints/main/routes.py`** — aggiunto endpoint
  `manifest()` registrato su `/manifest.webmanifest`
- **`stoic_eln/templates/base.html`** — aggiunti i 7 tag PWA nel
  `<head>` accanto al favicon esistente

### i18n

Nessuna traduzione nuova. Il manifest contiene una description
in inglese (non viene mostrata all'utente, è metadata per gli
store) e categorie standard PWA (`productivity`, `science`).

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-pwa-patch.tar.gz -C ~/Projects/
make test 2>&1 | tail -3
```

Atteso: **582 passed** (571 + 11).

Niente migration, niente script post-install.

## Verifica visiva

### Su Mac (sviluppo)

```
make run
```

Apri Chrome (NON Safari su Mac — i devtools PWA di Chrome sono
migliori): vai su `localhost:5001`. Apri devtools → Application
tab → Manifest. Dovresti vedere il manifest renderizzato con tutte
le icone, il colore, il nome correttamente. Eventuali warning
(ad es. "no icons of size X") sono indicatori utili.

### Su iPad/iPhone

1. Apri Safari sull'iPad
2. Vai a `http://<tuo-ip-locale>:5001` (Stoic sul Mac deve essere
   accessibile dalla rete: aggiungi `host="0.0.0.0"` nel make run
   se necessario, oppure usa un ngrok per il primo test)
3. Tap sull'icona di condivisione (quadrato con freccia verso alto)
4. Scroll giù → "Aggiungi alla schermata Home"
5. Tocca "Aggiungi"
6. L'icona di Stoic appare sulla home dell'iPad
7. Tappa l'icona → Stoic si apre a tutto schermo

### Su Android

Stesso pattern con Chrome: menu (tre puntini) → "Installa app" o
"Aggiungi a Home Screen".

## Cosa NON è in questa patch

- **Offline support / Service Worker** — è un capitolo a parte che
  richiede strategy di cache e migration di asset. Possiamo
  affrontarlo dopo se serve.
- **Push notifications** — fuori scope, ne parliamo solo se
  emerge un caso d'uso (es. notifica quando un backup fallisce).
- **App Store native** — Stoic resta una webapp, non un'app
  nativa pubblicata su App Store/Play Store. La PWA è "abbastanza
  vicina" per il caso d'uso laboratorio.
