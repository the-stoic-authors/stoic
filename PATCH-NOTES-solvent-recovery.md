# Patch v1.5.0 — recupero solventi (green chemistry, parte 1)

Registra il solvente che recuperi al rotavapor come lotto vero di
inventario. Prima parte: **produrre** i lotti recuperati. Consumarli
(prelievi elastici multi-fonte, soglia soft di riuso) è v1.5.1.

## Le quattro decisioni di dominio

Prese con Rico prima di scrivere una riga:

1. **Il recupero si registra sullo step dove avviene**, non a fine run.
   Lo step sa quali lotti sono confluiti, quindi il recuperato porta
   una composizione invece di essere un volume anonimo. A fine run
   avresti un totale per solvente e perderesti la composizione proprio
   dove recuperare conviene di più.
2. **Un solo meccanismo, due esiti**: un componente spuntato → lotto di
   `Substance`; più d'uno → lotto di `Mixture` con composizione v/v.
3. **Anagrafica deduplicata per composizione arrotondata al 10% v/v**.
   Cinquanta colonne a 90:10 → una riga in anagrafica, cinquanta lotti.
4. **Il vincolo di riuso (`origin_reaction_id`) sta sul lotto**, non
   sulla miscela: la miscela è una voce di catalogo condivisa, "riusabile
   solo in questa reazione" è una proprietà della bottiglia.

## Perché le checkbox e non una regola

Uno step di estrazione ha DCM **e** acqua. Tu tieni la fase organica e
butti quella acquosa. Se Stoic sommasse tutti i solventi dello step,
creerebbe un lotto "DCM/acqua 70:30" che non esiste in natura — e
siccome i lotti recuperati si riusano, quell'errore tornerebbe indietro
in una colonna futura.

Dedurlo automaticamente richiederebbe sapere quali sostanze sono
acquose: Stoic ha `state` e `density`, non la miscibilità. Una regola
su lista di nomi ("acqua, brine, NaHCO₃ sat.") funzionerebbe finché
qualcuno non chiama una miscela diversamente, e fallirebbe in silenzio.

Quindi: checkbox esplicite, pre-spuntate sui componenti con ruolo
solvente. Un clic in più, e la composizione riflette quello che hai
davvero in bottiglia.

## Perché l'arrotondamento al 10%

Due colonne non danno mai la stessa composizione esatta, e non solo per
il gradiente: quello che raccogli è una media integrata su tutte le
frazioni. Confrontando le composizioni al valore esatto la
deduplicazione non scatterebbe mai e l'anagrafica crescerebbe di una
riga per colonna.

Scelta di Rico fra passi del 5% e del 10%: **10%**, più vicino a come un
recuperato viene trattato davvero al banco.

Nota implementativa: l'arrotondamento non somma sempre a 100 (33/33/33 →
30/30/30), quindi la quota maggiore assorbe il resto. Un componente che
arrotonda a zero viene scartato: sotto il 5% del volume non definisce il
solvente che hai in mano.

## Perché il contatore usi segue il peggiore

Se in una colonna confluiscono EtOAc vergine (0 usi) ed esano già
recuperato due volte (2 usi), il lotto nasce con **3**, non con la media.

La media pesata sui volumi si leggerebbe meglio ma nasconderebbe proprio
la cosa che il contatore esiste per segnalare: le impurità non volatili
si accumulano, e aggiungere solvente fresco le diluisce senza
rimuoverle. Se il conteggio dev'essere sbagliato, meglio per eccesso.

## Cosa cambia nel codice

- **`services/solvent_recovery.py`** (nuovo) — `recoverable_components()`,
  `register_recovery()`, la firma di composizione per il dedup e la
  generazione del codice lotto (`RX-2026-0500-REC1`).
- **`InventoryItem`** + `is_recovered`, `recovery_use_count`,
  `recovered_at`, `recovered_from_step_id`, `origin_reaction_id`.
- **`Mixture`** + `is_recovered`, `recovery_signature` (chiave di dedup
  costruita su id di sostanza, non su nomi: rinominare una sostanza non
  forka il catalogo).
- **Route** `runs.recover_solvent` — form POST classico con pulsante.
  Non HTMX su `change`: con un campo auto-salvante digiti "5" e ti
  ritrovi un lotto da 5 mL prima di aver finito di scrivere "50".
- **`runs/detail.html`** — sezione *Solvente recuperato* nella card
  step, visibile solo a run in corso.
- Il lotto recuperato eredita il gruppo dai lotti di provenienza, come
  già fa una preparazione in `prep_service`.

## Migrazione — OBBLIGATORIA

    export FLASK_APP=stoic_eln
    .venv/bin/flask migrate-solvent-recovery

Sette colonne su due tabelle. I due flag NOT NULL hanno un DEFAULT,
quindi le righe esistenti si backfillano da sole: un lotto già in
inventario non è recuperato e ha zero riusi. Idempotente, testata contro
uno schema vecchio con dati dentro.

Su stoichub, al ritorno: `docker compose exec stoic flask
migrate-solvent-recovery`.

## Test

22 test nuovi in `tests/test_solvent_recovery.py`: candidati al
recupero, acqua offerta ma non pre-spuntata, voci libere escluse,
composizione arrotondata, lotto singolo vs miscela, acqua non spuntata
che non entra mai, dedup del catalogo, percentuali che sommano a 100,
contatore al caso peggiore, provenienza e vincolo di riuso, codici
lotto incrementali, gruppo ereditato, quattro rifiuti, due sulla
migrazione, tre dalle route HTTP.

Sandbox: **733 verdi** (711 + 22, `test_pubchem` escluso).

Validati per mutazione: contatore usi come media → cade 1 test;
composizione da tutti i componenti ignorando le checkbox → cadono 2;
dedup disattivata → cade 1.

## Trovato verificando le traduzioni a runtime

La stringa inglese del flash conteneva `\\u201c` come escape: i `.po`
non interpretano gli escape unicode, quindi un utente EN avrebbe letto
`Created mixture \\u201c...\\u201d`. `pybabel compile` non se ne accorge.
Corretto con le virgolette curve reali. È il motivo per cui la regola
dice di verificare con `gettext` in entrambe le lingue.

## Cosa NON fa questa patch

- Non consuma i lotti recuperati: prelievi elastici multi-fonte e
  filtro per `origin_reaction_id` sono **v1.5.1**
- Nessuna soglia soft di riuso (decisa: default globale 3 + override
  opzionale sul template) — arriva con il consumo, perché è lì che il
  warning ha senso
- Nessuna metrica green (E-factor, atom economy, PMI): spostate a
  **v1.6.0**, sono reporting e non devono bloccare il rilascio del
  recupero
