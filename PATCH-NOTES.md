# Stoic — patch 15.2 (installer macOS autonomo)

Aggiunge `scripts/installers/install-macos.sh`: un installer
one-shot che porta un Mac fresco da "niente" a "Stoic in
esecuzione e pronto a login" con un solo comando.

## Cosa fa

```bash
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-macos.sh | bash
```

In ordine:

1. Verifica macOS (rifiuta Linux/Windows).
2. Installa Homebrew se mancante.
3. Installa via brew: `python@3.12`, `cairo`, `pkg-config`,
   `freetype`, `libpng`. Le librerie native servono per le
   dipendenze Python (`pycairo` via `rlPyCairo` per SVG GHS,
   Pillow per le immagini).
4. Clona la repo in `~/Projects/stoic-eln` (o pull se già
   presente, con safety check su working tree).
5. Crea `.venv` con `python@3.12`, esegue `pip install -e .`.
6. Inizializza il DB (`flask init-db`).
7. Prompt per il primo utente admin (skipped se già ci sono
   utenti — idempotente).
8. Stampa istruzioni per i prossimi passi (foreground vs
   daemon).

Idempotente: ri-eseguibile senza danni. Salta quello che è già
fatto.

## Decisioni di design

**Detection Intel vs Apple Silicon.** Homebrew installa in
`/opt/homebrew` su ARM e `/usr/local` su Intel. Lo script
prova entrambe le strade per trovare `python3.12` dopo l'install,
non assume una. Funziona su MacBook Pro Intel x86_64 (tuo) e
MacBook M-series moderni.

**Niente sudo se possibile.** Homebrew chiede password solo se è
il primo install assoluto sulla macchina; il resto dello script
gira come l'utente normale. Nessuna modifica a `/etc/hosts`,
firewall, o cose di sistema.

**Porta 5001.** Default scelto per non scontrarsi con AirPlay
Receiver di macOS (5000). Override via `STOIC_PORT=5000` se
l'utente disabilita AirPlay.

**Override via env vars.** Tutti i parametri configurabili
(`STOIC_REPO`, `STOIC_DIR`, `STOIC_BRANCH`, `STOIC_PORT`)
esposti come variabili d'ambiente, così sviluppatori possono
testare branch alternativi senza modificare lo script.

**Output coerente con il CLI.** Stessi prefissi `✓ → ⚠ ✗`
colorati, rispetta `STOIC_NO_COLOR` come il CLI `stoic`.

**Non disabilita AirPlay** — è una scelta dell'utente, non
dell'installer.

**Non installa come root.** Il primo admin è creato come utente
applicativo (Stoic ha il suo sistema di account), non come root.

## File aggiunti

- `scripts/installers/install-macos.sh` (~ 200 righe, eseguibile)
- `scripts/installers/README.md` — documentazione utente

## Applicazione

```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-eln-patch15.2.tar.gz -C ~/Projects/
chmod +x scripts/installers/install-macos.sh
```

## Test sul tuo Mac

Non testare lo script così com'è — è progettato per macchine
fresche. La tua installazione esistente verrebbe semplicemente
"pullata" (step 4) e l'install-e ripetuto (step 5). Per provare
in sicurezza:

```bash
# Test "dry run" in una directory diversa
STOIC_DIR=/tmp/stoic-test-install \
STOIC_REPO=$HOME/Projects/stoic-eln \
bash scripts/installers/install-macos.sh
```

Questo clona il **tuo** repo locale (non quello remoto, che non
esiste ancora) in `/tmp/stoic-test-install`, e fa l'install da
zero lì. Quando hai verificato che funziona, puoi `rm -rf
/tmp/stoic-test-install`.

NOTA: il clone funziona solo se il tuo `~/Projects/stoic-eln` ha
un commit di Git (vediamo `git log -1` sul tuo Mac). Se non è un
git repo ancora, lo script fallirà alla clone — questo è un test
del path "installer fresh on virgin machine". Possiamo creare un
repo locale separato per test.

## Prossime patch Settimana 7

- **15.3** — `install-linux.sh` per Debian/Ubuntu/Raspberry Pi
  Raspbian. Pattern uguale ma con `apt` invece di `brew`, e
  systemd user services invece di launchd.
- **15.4** — Push iniziale su GitHub `the-stoic-authors/stoic` +
  release v1.0.0 con landing page GitHub Pages.
