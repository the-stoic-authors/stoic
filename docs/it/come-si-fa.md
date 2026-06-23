# Stoic ELN — Come si fa

Guida rapida ai workflow più comuni. Passi numerati, niente teoria.
Per i concetti di base vedi il [Manuale utente](manuale-utente.md).

---

## Aggiungere una sostanza manualmente

1. Sidebar → **Sostanze** → **Nuova sostanza**
2. Scegli **Inserimento manuale**
3. Compila almeno: nome, peso molecolare, stato fisico
4. Aggiungi CAS, SMILES, densità se disponibili
5. Nella sezione **Sicurezza**: seleziona pittogrammi GHS, inserisci frasi H e P
6. **Salva**

> Le frasi H/P appaiono sulle etichette lotto — inserirle subito
> evita di tornare in seguito.

---

## Aggiungere una sostanza da PubChem

1. Sidebar → **Sostanze** → **Nuova sostanza**
2. Scegli **Importa da PubChem**
3. Incolla CAS, nome IUPAC o SMILES nel campo di ricerca
4. Seleziona il risultato corretto dall'elenco
5. Verifica i dati pre-compilati (MW, densità, GHS)
6. Correggi eventuali errori (PubChem non è sempre accurato su densità e stato)
7. **Salva**

> Per composti sintetici non in PubChem usa l'inserimento manuale.

---

## Gestione ordini

### Pianificare un ordine
1. Apri la pagina della sostanza da ordinare
2. Clic **Pianifica nuovo ordine**
3. Inserisci quantità, fornitore, codice catalogo, costo stimato, data prevista
4. **Salva** → ordine in stato `pianificato`

### Confermare l'ordine inviato
1. Apri l'ordine → clic **Marca come ordinato**
2. Lo stato passa a `ordinato` (da qui non è più modificabile)

### Ricevere un ordine
1. Apri l'ordine → clic **Ricevi**
2. Inserisci: quantità ricevuta, costo finale, lotto fornitore, scadenza
3. **Conferma** → Stoic crea automaticamente il lotto in inventario

---

## Aggiungere una sostanza all'inventario (lotto)

Per aggiungere un lotto senza passare dal modulo ordini (es. reagente
già in laboratorio):

1. Apri la pagina della sostanza
2. Clic **Aggiungi lotto**
3. Inserisci: quantità, unità, fornitore, numero lotto fornitore, scadenza, costo
4. **Salva**

Il lotto appare nella lista inventario della sostanza ed è disponibile
per i run.

---

## Creare una miscela (ricetta)

Una miscela è una "ricetta" riutilizzabile (es. HCl 1N, EtOAc/Esano 3:7).

1. Sidebar → **Miscele** → **Nuova miscela**
2. Assegna un nome descrittivo (es. `HCl 1N acquoso`)
3. Aggiungi i componenti: per ognuno cerca la sostanza, inserisci
   il rapporto (es. mL/L o % v/v) e il ruolo
4. Aggiungi note di preparazione se utile
5. **Salva**

La miscela è ora disponibile come reagente nelle reazioni e nelle procedure.

---

## Preparare una miscela (esecuzione)

1. Apri la miscela → clic **Nuova preparazione**
2. Inserisci il volume target (es. 500 mL)
3. Stoic calcola le quantità di ogni componente
4. Seleziona i lotti da usare per ogni componente
5. Prepara fisicamente la miscela
6. Inserisci la quantità effettiva ottenuta
7. **Completa preparazione**

Stoic crea un lotto della miscela usabile in inventario e nei run.

---

## Aggiungere una miscela all'inventario (lotto)

Per registrare un lotto di miscela già preparato esternamente
(es. tampone commerciale, soluzione ricevuta):

1. Apri la miscela → clic **Aggiungi lotto**
2. Inserisci: quantità, unità, data preparazione/ricezione, scadenza
3. **Salva**

---

## Creare un template di reazione

1. Sidebar → **Reazioni** → **Nuova reazione**
2. Assegna un nome (es. `Esterificazione Fischer — acido acetico/metanolo`)
3. Aggiungi i componenti:
   - **Starting material**: il limite stechiometrico (1 eq)
   - **Reagenti/Reattivi**: inserisci gli equivalenti rispetto allo SM
   - **Catalizzatori, basi, acidi**: inserisci eq o % mol
   - **Solventi**: inserisci mL/mmol
   - **Prodotto atteso**: inserisci eq teorici (di solito 1.0)
4. Aggiungi le fasi di workup come **Step** (estrazione, purificazione, analisi)
5. Clic **Pubblica** quando il template è pronto per l'uso

> Un template in bozza non può essere eseguito. Pubblica solo quando
> la procedura è consolidata.

---

## Salvare una procedura in libreria

Per salvare uno step di workup/purificazione come procedura riutilizzabile:

1. Apri il template di reazione che contiene lo step
2. Nell'intestazione dello step → clic **Salva in libreria**
3. Assegna un nome univoco (es. `Flash cromatografia Still — 30 g/g`)
4. **Salva**

La procedura è ora disponibile per tutti i template del laboratorio.

---

## Usare una procedura nelle reazioni

1. Apri il template di reazione in modalità modifica
2. Nella sezione **Step** → clic **Aggiungi step da libreria**
3. Seleziona la procedura dall'elenco
4. Lo step viene copiato nel template (modificabile indipendentemente)

> Modificare la libreria in seguito **non** cambia i template che
> hanno già copiato la procedura. È intenzionale: la riproducibilità
> storica è garantita.

---

## Eseguire un run

### Creare il run
1. Apri il template di reazione → clic **Nuovo run**
2. Stoic crea una bozza con tutti i componenti copiati dal template

### Impostare la scala
1. Nel run, inserisci la massa (o mmol) dello **starting material**
2. Stoic ricalcola automaticamente tutte le quantità

### Assegnare i lotti
1. Per ogni componente, seleziona il lotto dal menu a tendina
2. Se un lotto non appare, verificare che la sostanza sia in inventario
   con quantità > 0

### Avviare il run
1. Clic **Avvia run** — da questo momento il run è in esecuzione
2. Durante l'esecuzione puoi:
   - Registrare le quantità effettive pesate
   - Aggiungere step al volo (clic **Aggiungi step** in fondo)
   - Registrare parametri di processo (temperatura, pressione, ecc.)
   - Spuntare le voci della checklist
   - Aggiungere note di esecuzione

### Completare il run
1. Pesa il prodotto e inserisci la massa nella riga **Prodotto**
2. La resa viene calcolata automaticamente
3. Aggiungi allegati finali (NMR, HPLC, foto)
4. Clic **Completa run**

Il run è ora immutabile. Stoic crea un lotto del prodotto in inventario.

### Modalità banco (tablet)
Sul tablet al banco: clic **Modalità banco** nell'intestazione del run.
La sidebar sparisce, i tasti ingrandiscono, il font cresce. Clic
**Esci** per tornare alla visualizzazione normale.

---

## Configurare il backup

### Backup automatico
1. Sidebar → **Impostazioni** → **Backup**
2. Attiva **Backup automatico**
3. Imposta ora di esecuzione (default: 03:00) e giorni di retention
4. **Salva configurazione**

### Backup off-site (consigliato)
1. Monta il volume esterno sul server (NAS, chiavetta, disco) via
   `fstab` o `systemd.mount` — Stoic non monta volumi da solo
2. In **Impostazioni → Backup**: attiva **Copia off-site**
3. Inserisci il percorso del mount (es. `/mnt/nas/stoic-backups`)
4. **Salva** → al prossimo backup Stoic copia il file anche lì

Se la copia off-site fallisce, il backup locale è già al sicuro e
appare un avviso giallo. Il backup non viene mai abortito per un
errore off-site.

### Backup manuale
In **Impostazioni → Backup** → clic **Esegui backup ora**.

---

## Stampare un'etichetta lotto

1. Apri il lotto (da **Inventario** o dalla pagina della sostanza)
2. Clic **Stampa etichetta**
3. Scegli il formato:
   - **Avery L7160** — 24 etichette/foglio A4, per barattoli piccoli
   - **Avery L7164** — 12 etichette/foglio A4, struttura molecolare grande
   - **Termica 62 mm** — per stampanti Brother QL / Dymo
4. Apri il PDF e stampa

L'etichetta include: nome, IUPAC, CAS, MW, batch code, scadenza,
pittogrammi GHS, frasi H/P, QR code con link al lotto in Stoic.

---

## Ricerca globale (Cmd+K)

Per trovare qualsiasi entità nell'app in meno di due secondi:

1. Premi **Cmd+K** (Mac) o **Ctrl+K** (Windows/Linux) da qualsiasi pagina
2. Digita il nome, codice o identificatore
3. Stoic cerca in: sostanze, miscele, reazioni, run, ordini,
   preparazioni, lotti, note
4. Clic sul risultato o usa le frecce + Invio per navigare

> La ricerca è live: i risultati appaiono mentre scrivi, senza
> premere Invio.
