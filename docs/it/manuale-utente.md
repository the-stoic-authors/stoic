# Stoic ELN — Manuale utente

Stoic è un quaderno elettronico di laboratorio (ELN) per chimici.
Tiene traccia di sostanze, lotti, reazioni e run, calcola
stechiometria e rese, e genera etichette e report PDF.

Questo manuale è destinato all'utente di laboratorio (chi esegue
le reazioni). Per gli aspetti di configurazione e gestione utenti
vedi il manuale dell'amministratore.

---

## Concetti chiave

Stoic distingue cinque entità di base. Capirle è metà del lavoro:

**Sostanza.** Una specie chimica nel catalogo del laboratorio:
acido acetico, NaH, EtOAc, ecc. Una sola sostanza per InChIKey —
non duplicati. Ha proprietà fisiche (MW, densità, stato), dati di
sicurezza (GHS, frasi H/P) e identificatori (CAS, SMILES, IUPAC).

**Lotto** (`InventoryItem`). Una bottiglia fisica di una sostanza
specifica, con un codice batch, quantità residua, scadenza,
fornitore, costo. Una sostanza può avere più lotti (apri il
quinto barattolo di NaH? è un lotto nuovo).

**Miscela** (`Mixture`). Una preparazione fisica composta da una o
più sostanze: soluzione (HCl 1N), eluente (EtOAc/Esano 1:1),
tampone (PBS pH 7.4). Anche le miscele hanno lotti (vedi sotto)
e possono essere usate in reazioni come reagenti.

**Reazione** (template). Una "ricetta" generica: SM + reagenti →
prodotto, con coefficienti stechiometrici, scala di riferimento e
procedura. È il *template*, non una specifica esecuzione. Una
reazione può essere eseguita molte volte (run).

**Run**. Una singola esecuzione di una reazione. Specifica scale
effettiva, lotti utilizzati, pesi reali misurati, resa, note. È
immutabile una volta completata (tranne aggiunte additive come
note).

---

## Inizia da qui — primo login

Quando un amministratore ti ha creato l'account, ricevi username
e password temporanea. Al primo login Stoic ti chiede di cambiarla:

1. Apri Stoic nel browser
2. Login con username + password temporanea
3. Vai su **Profilo → Cambia password** (in alto a destra)
4. Imposta una password di almeno 8 caratteri

Da qui in poi sei operativo. La dashboard mostra: avvisi (sostanze
sotto soglia, lotti in scadenza), ultimi run, statistiche.

---

## Il workflow tipico di una giornata in laboratorio

Esempio concreto: vuoi fare una reazione di esterificazione.

### 1. Verifica disponibilità sostanze e lotti

Vai su **Sostanze** dalla sidebar. Cerca l'acido carbossilico, il
metanolo, il catalizzatore. Per ognuno, controlla:

- **Esiste nel catalogo?** Se no, aggiungila (vedi sotto)
- **Hai un lotto con quantità sufficiente?** Apri la pagina della
  sostanza, vedi i lotti elencati con quantità residua e scadenza

Se manca una sostanza nel catalogo, clic su **Nuova sostanza**.
Hai due opzioni:

- **Import da PubChem**: due modalità nella stessa pagina.
  - *Testo*: incolla CAS, nome, SMILES, InChI, InChIKey o CID;
    Stoic tira giù proprietà, GHS e identificatori. Se il nome è
    ambiguo (es. "glucose"), Stoic mostra una lista di candidati con
    la struttura disegnata, così scegli l'isomero corretto a colpo
    d'occhio invece di prendere alla cieca il primo risultato.
  - *Disegna*: apri la tab **Disegna** e costruisci la molecola con
    l'editor. Stoic genera lo SMILES e cerca il composto su PubChem.
    Comodo quando conosci la struttura ma non il nome esatto.
  Verifica sempre che i dati scaricati siano corretti prima di salvare.
- **Inserimento manuale**: compila i campi a mano. Utile per
  composti non in PubChem (intermedi sintetici, sostanze custom).

Se manca un lotto, vai in **Inventario** → **Nuovo lotto** e
registralo (data acquisto, quantità ricevuta, scadenza, fornitore,
costo).

### 2. Crea o trova la reazione template

Vai su **Reazioni**. Se la trasformazione esiste già come template
(qualcuno l'ha fatta prima), aprila. Altrimenti **Nuova reazione**:

- Titolo descrittivo: "Esterificazione di Fischer con MeOH"
- Codice breve (es. `EST-MEOH`): generato automaticamente, puoi
  personalizzarlo
- SMILES di reazione (opzionale): `O=C(O)CCC>>O=C(OC)CCC` per
  esempio. Stoic deriverà lo schema visivo da qui se compilato.
- Aggiungi i **componenti**: sostanza, ruolo (SM/reagente/prodotto/
  solvente/catalizzatore/altro), equivalenti, e per ognuno se è
  fissato in g o mL o ad lib (`quanto basta`, tipico per solventi
  di cromatografia)
- **Prodotti e sottoprodotti — "Salva in inventario"**: ogni
  prodotto e sottoprodotto ha un interruttore *Inventario*. Se
  attivo, al completamento del run quel componente crea un lotto in
  inventario e conta nel calcolo della resa. I **prodotti** sono
  attivi di default (sono ciò che vuoi produrre); i **sottoprodotti**
  sono disattivi di default, perché di solito sono scarti. Esempio:
  nella generazione di HCl (NaCl + H₂SO₄ → HCl + NaHSO₄) vuoi l'HCl
  in inventario, non il bisolfato di sodio — altrimenti l'inventario
  si riempie di NaHSO₄ a ogni run. Un componente escluso
  dall'inventario è escluso **anche dalla resa**: la resa è sul
  prodotto, non sugli scarti. Se un sottoprodotto è invece
  recuperabile e vuoi tracciarlo, attiva l'interruttore.
- Aggiungi **step** opzionali (procedura): "Sciogliere SM in MeOH",
  "Aggiungere H2SO4 catalitico", "Riflusso 12 h", ecc.
- Aggiungi **workup** e **checklist** se vuoi (azioni di routine
  da spuntare durante l'esecuzione)
- **Pubblica** la reazione quando sei soddisfatto. Solo le reazioni
  pubblicate possono essere usate per nuovi run.

### 3. Crea il run

Dalla pagina della reazione, clicca **Nuovo run**.

- **Scala**: scegli un riferimento (di solito un componente con
  ruolo SM) e una quantità target (es. 5 mmol). Stoic calcola
  automaticamente le quantità di tutti gli altri componenti.
- **Lotti**: per ogni componente con ruolo non-prodotto, scegli
  il lotto da cui prelevare. Stoic ti mostra solo lotti con
  quantità sufficiente.
- **Pesi reali**: pesa i reagenti, inserisci i valori in g/mL
  effettivi misurati. Stoic ricalcola moli ed equivalenti in
  tempo reale.
- **Allegati**: puoi caricare foto del setup, screenshot di
  bilancia, prima di iniziare.

### 4. Avvia il run

Quando hai tutto pronto, clic su **Avvia esecuzione**. Da qui:

- L'inventario viene aggiornato (la quantità dei lotti scende delle
  quantità prelevate)
- I pesi dei reagenti diventano immutabili (puoi modificare solo
  prodotti, note, checklist)
- Lo stato del run passa da `draft` a `in_progress`

Mentre il run è in corso, spunta le voci della checklist man mano
che le completi. Aggiungi note libere se serve (es. "TLC dopo 4h
mostra ancora SM, prolungo riflusso").

### 5. Completa il run

Quando hai isolato il prodotto:

- Pesa il prodotto, inserisci la quantità nei componenti con ruolo
  Prodotto
- Resa viene calcolata automaticamente (mol prodotto / mol SM × 100)
- Carica eventuali allegati finali: NMR, HPLC, foto del prodotto
- Clic su **Completa run** in fondo alla pagina

Da qui il run è immutabile. Stoic crea automaticamente un nuovo
lotto del prodotto in inventario, con codice batch generato (es.
`EST-MEOH-2026-001`).

### 6. Stampa etichetta

Vai sul nuovo lotto in inventario, clic **Stampa etichetta**.
Scegli formato:

- **Avery L7160** (24 etichette per foglio A4, 63.5 × 33.9 mm) —
  formato compatto, va su barattoli piccoli
- **Avery L7164** (12 etichette per foglio, 63.5 × 72 mm) — più
  spazio, include struttura molecolare grande
- **Termica 62 mm** (Brother QL / Dymo) — singola etichetta per
  pagina, ideale per stampanti termiche

Ogni etichetta include: nome sostanza, IUPAC, codice batch, data
scadenza, CAS, formula, MW, densità (se nota), pittogrammi GHS,
codici frasi H/P, e un QR code che decodifica all'URL del lotto
in Stoic.

Stampa quante copie servono. Per Avery puoi scegliere "Inizia da
posizione N" se stai riutilizzando un foglio parzialmente usato.

---

## Workflow: preparazione di una miscela

Le miscele (soluzioni, eluenti, tamponi) sono entità di prima
classe in Stoic. Esempio: vuoi preparare 500 mL di HCl 1N partendo
da uno stock 6N.

### 1. Crea la miscela "ricetta"

Vai su **Miscele** → **Nuova miscela**:

- **Nome**: "HCl 1N"
- **Tipo**: Soluzione
- **Concentrazione principale**: 1.0 N
- **Solvente principale**: Acqua (scegli dalla picker)
- Aggiungi **componenti** strutturati (opzionale): SM (acido
  cloridrico) con concentrazione 1.0 N
- **Salva**

Adesso "HCl 1N" è nel catalogo delle miscele, ma nessun lotto
fisico esiste ancora.

### 2. Esegui la preparazione

Dalla pagina della miscela, clic **Prepara**. Inserisci:

- **Quantità target**: 500 mL
- **Lotti precursori**: per ogni componente, scegli il lotto da
  cui prelevare. Per HCl 6N, scegli il lotto in inventario.
- Stoic ti mostra **quanto prelevare di ciascuno** (per HCl 6N:
  500 mL × 1 N / 6 N = 83.3 mL)
- Conferma con **Esegui preparazione**

Stoic crea:
- Un nuovo lotto della miscela "HCl 1N" con quantità 500 mL e
  codice batch (es. `HCL1N-2026-001`)
- Aggiornamento dell'inventario: il lotto di HCl 6N scende di 83.3 mL

Da qui in poi puoi usare il nuovo lotto di HCl 1N in reazioni
come qualunque altro lotto, e stampare etichette dal lotto creato.

### Strategie di calcolo automatico

Stoic riconosce tre tipi di ricetta e calcola di conseguenza:

| Strategia | Quando si attiva | Esempio |
|-----------|-----------------|---------|
| **Diluizione** | Un solo soluto + concentrazione principale impostata sulla miscela | HCl 1N da HCl 6N |
| **Concentrazione massa** | Uno o più soluti con unità `g/L` o `mg/mL` **e concentrazione principale vuota** | NaCl 400 g/L (salamoia) |
| **Ratio / %** | Componenti in `ratio`, `%v/v`, `%w/w` o `%w/v` | EtOAc/Esano 3:7 |

> **Importante**: il campo "Concentrazione principale" della miscela va compilato **solo per le diluizioni da stock** (es. HCl 1N da HCl 6N). Per le ricette a dissoluzione diretta (es. NaCl solido in acqua), lasciarlo **vuoto** — altrimenti Stoic tenta la diluizione invece del calcolo massa.

Per le ricette a **concentrazione di massa** (es. salamoia):
- Inserisci il soluto con ruolo `Soluto` e concentrazione `400 g/L`
- Inserisci il solvente (acqua) con ruolo `Solvente` e concentrazione vuota
- Stoic proporrà: **400 g di NaCl** + **1 L d'acqua** per portare a volume

---

## Libreria procedure

Le procedure ripetitive (workup acquoso, filtrazione su celite,
flash chromatography…) si salvano una volta e si riusano ovunque.

**Salvare**: in un protocollo in bozza, ogni passo ha l'icona
libreria 📚 nell'intestazione. Cliccala, dai un nome, salva.
Componenti e checklist entrano nella libreria del laboratorio.

**Riusare**: nel modal "Nuovo passo" di qualunque protocollo in
bozza compare "…oppure inserisci dalla libreria procedure".
Scegli e inserisci: la procedura viene COPIATA nel protocollo.

**Modificare**: la libreria si modifica passando per un
protocollo: inserisci la procedura, sistemala, ri-salvala con lo
stesso nome spuntando "sovrascrivi". I protocolli che usavano la
versione precedente NON cambiano — ogni protocollo conserva la
copia con cui è stato costruito, come i Run congelano i template.

La pagina **Procedure** nel menu mostra la libreria completa, con
rinomina ed eliminazione (eliminare dalla libreria non tocca mai
i protocolli).

## Voci libere nei passi

Oltre a sostanze e miscele, un passo può contenere **voci fuori
inventario**: il diametro della colonna, la celite, il ghiaccio.
Nel form "Aggiungi componente" scegli "Voce libera", dai nome e
unità di misura libera (mm, g, CV, quello che serve).

Quantità disponibili per le voci libere:

  - **valore fisso** — un numero nella tua unità ("Celite, 5 g")
  - **quanto basta** — nessun valore nel template, registri al Run
  - **Ø colonna (h letto, cm)** — il diametro viene CALCOLATO:
    il valore che inserisci è l'altezza del letto di silice in cm
    (15 è lo standard flash); Stoic trova il componente con ruolo
    "fase stazionaria" nello stesso passo, ne prende la massa alla
    scala del Run e calcola il diametro dalla geometria del
    cilindro (densità silice 0.5 g/mL). Nel Run appare come
    "suggerito: 23 mm" — arrotonda alla colonna che possiedi.
    Raddoppiare la scala allarga il diametro di √2, com'è giusto.

## Allegati

Ogni run, reazione template, sostanza, lotto, miscela e
preparazione può avere allegati. Tipologie tipiche:

| Entità | Tipo allegati |
|---|---|
| Run | NMR, HPLC, MS, foto setup, foto TLC, CoA prodotto |
| Reazione (template) | SOP, procedura annotata, articolo riferimento |
| Sostanza | SDS del fornitore, CoA generale |
| Lotto | label, foto barattolo, CoA del lotto |
| Miscela | SOP della ricetta, foto del bottiglione |
| Preparazione | CoA del prodotto, foto setup, calibrazione |

**Tipi di file accettati**: PDF, immagini (jpg/png/gif/webp), dati
laboratorio (csv, xlsx, jdx, mol, raw, mzML, ecc.), archivi .zip.

**Tipi rifiutati**: eseguibili, HTML, JavaScript, SVG (per
sicurezza). Massimo 100 MB per file.

**Dedup automatico**: se carichi due volte lo stesso file (stesso
contenuto), Stoic lo riconosce via SHA-256 e tiene un solo file
fisico su disco, con due riferimenti.

**Eliminazione**: chi ha caricato l'allegato può eliminarlo. Gli
amministratori possono eliminare allegati di chiunque. Tutte le
operazioni sono tracciate nell'audit log.

---

## Workflow: gestione ordini

Stoic ha un modulo ordini integrato per pianificare e ricevere
acquisti.

### 1. Pianifica un ordine

Dalla pagina di una sostanza, clic **Pianifica nuovo ordine**.
Inserisci:

- Quantità (g o mL, in base allo stato fisico)
- Fornitore, codice catalogo, costo stimato
- Data consegna prevista

L'ordine entra in stato `planned`.

### 2. Conferma ordinato

Quando hai inviato l'ordine al fornitore (telefono, email, sistema
acquisti aziendale), torna sull'ordine e clic **Marca come
ordinato**. Lo stato passa a `ordered`. Da qui in poi non puoi più
modificarne i dettagli.

### 3. Ricevi l'ordine

Quando l'ordine arriva, clic **Ricevi**. Inserisci:

- Quantità effettivamente ricevuta (può differire dal pianificato)
- Costo finale (può differire dalla stima)
- Numero di lotto del fornitore
- Data ricezione, scadenza dal fornitore

Stoic crea automaticamente un nuovo `InventoryItem` (lotto) con
questi dati. L'ordine passa a `received`.

### 4. Lista della spesa

Dalla dashboard o dal menu Ordini, c'è la voce **Lista della
spesa**: tutte le sostanze sotto soglia minima, con quantità
suggerita (soglia + 50% buffer), ultimo fornitore e costo unitario
stimato. Comodo da stampare/copiare per fare ordini bulk.

---

## Rubrica fornitori

Dalla versione 1.1, Stoic ha una rubrica dedicata ai fornitori del
laboratorio, accessibile dalla voce **Fornitori** in sidebar.

### Cosa puoi salvare

Per ogni fornitore: nome, indirizzo, telefono, email, sito web /
portale ordini, username e password del portale, e note libere
(condizioni di pagamento, contatto commerciale, ecc.).

> Username e password del portale sono salvati in chiaro nel
> database. Su un'installazione self-hosted con disco cifrato (come
> raccomandato per stoichub) questo è un compromesso accettabile —
> non è comunque un sostituto di un password manager dedicato per
> credenziali ad alto rischio.

### Usare un fornitore in un ordine

Quando pianifichi un nuovo ordine, il campo **Fornitore** mostra un
menu a tendina con i fornitori in rubrica, oltre al campo di testo
libero per fornitori occasionali non ancora salvati. Selezionando un
fornitore dalla rubrica, appare un riquadro con email, telefono e
link diretto al portale ordini — utile per non dover cercare le
credenziali altrove mentre si compila l'ordine.

### Ordini raggruppati per fornitore

Dalla pagina di dettaglio di un fornitore (clic sul nome dalla
rubrica) vedi tutti gli ordini collegati a quel fornitore, in
qualsiasi stato. È utile quando più persone del laboratorio hanno
bisogno di reagenti dallo stesso fornitore: puoi vedere tutto quello
che è pianificato e fare un unico ordine cumulativo, invece di
diversi ordini separati con relative spese di spedizione multiple.

---

## Dashboard e statistiche

La home di Stoic mostra:

- **Avvisi**: sostanze sotto soglia, lotti in scadenza nei
  prossimi 30 giorni, lotti scaduti
- **Ultimi run**: ultimi 10 run eseguiti, ordinati per data
- **Statistiche**: numero totale di sostanze/reazioni/run, rese
  medie, sostanze più usate

Dalla statistiche puoi anche andare in **Trend** per vedere
grafici di consumo nel tempo per ciascuna sostanza.

---

## Cosa fare se…

**Ho sbagliato un peso reale dopo aver avviato il run.** Se il run
è ancora in `in_progress`, i pesi dei reagenti sono congelati e
non puoi modificarli direttamente. Devi annullare il run (bottone
in fondo alla pagina) e ripeterlo dall'inizio. Annullare ripristina
le quantità dei lotti.

**Voglio annullare un run completato (resa zero, prodotto perso).**
Non si può. Una volta completato, il run è permanente. Puoi
aggiungere note ("Workup fallito, prodotto perso in colonna")
e marcare il run come "fallito" creando un nuovo run identico e
completandolo con resa 0.

**Ho duplicato per sbaglio una sostanza.** Le sostanze sono
deduplicate per InChIKey: non puoi creare un duplicato esatto.
Se hai due record per la stessa molecola con InChIKey diversi
(es. con/senza isotopi), gli amministratori possono fonderli.

**Una sostanza non è in PubChem.** Aggiungila a mano. I campi
strettamente obbligatori sono: nome, formula, MW. SMILES e
identificatori sono fortemente raccomandati. GHS puoi lasciarli
vuoti se non li conosci (verifica sempre la SDS del fornitore).

**Ho perso la passphrase di backup.** Se Stoic è configurato in
modo `prompt` (passphrase solo nella tua testa), i backup cifrati
sono persi. Contatta l'amministratore: può ripristinare uno stato
plain del DB, ma i backup cifrati storici non saranno recuperabili.

**Il DB sembra corrotto / Stoic non parte.** Contatta
l'amministratore. C'è quasi sempre un backup recente da ripristinare
(in `instance/backups/`). Non toccare manualmente `instance/
stoic_eln.db` — è un'operazione di sistema.

---

## Lingua

Stoic supporta italiano e inglese. Cambi lingua dal menu utente
(profilo). La preferenza viene salvata sul tuo account.

---

## Tema chiaro/scuro

Toggle nell'header. La preferenza viene salvata sul tuo account.

---

## Tasti rapidi

- `Ctrl+K` (`Cmd+K` su Mac): apre la barra di ricerca globale
  (sostanze, reazioni, lotti, run)
- `Esc` chiude i pop-up modali
- `Tab` naviga tra i campi delle form (standard browser)

---

## Sicurezza dei dati

Stoic può proteggere i dati di laboratorio con tre livelli:

1. **Backup automatici cifrati** ogni notte
2. **Cifratura del database live** (SQLCipher) — il file
   `stoic_eln.db` è opaco senza passphrase
3. **Passphrase solo in RAM** — chi prende il filesystem non trova
   la chiave

La configurazione spetta all'amministratore. Vedi il manuale
admin per i dettagli.

---

## Audit log

Tutte le azioni significative (create/edit/delete di sostanze,
reazioni, lotti, run, upload allegati) sono tracciate in un audit
log. Solo gli amministratori vedono il log completo, ma i tuoi
record sono sempre visibili a te dal tuo profilo.

Se elimini per sbaglio qualcosa (es. una sostanza), l'audit log
contiene l'evento. Chiedi all'amministratore di rivedere.
