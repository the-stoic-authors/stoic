# Stoic ELN — Aggiornamento alla Settimana 3

Aggiunge: gestione **reazioni** come template riutilizzabili, **calcolatore stechiometrico**
con scala configurabile, **disegno strutture** via SmilesDrawer 2.x bundlato localmente,
schemi di reazione automatici, **check list** sia a livello reazione che per ogni step,
**step modulari** (workup, estrazione, purificazione, analisi) con quantità calcolate
da ratio multipli (eq, mL/g, mL/mmol, %v/v, volume assoluto).

---

## Cosa c'è di nuovo

### Reazioni (template)
- Modello `Reaction` con codice progressivo automatico `RX-YYYY-NNNN`
- Campo `default_scale_mmol` (scala di default per anteprima quantità)
- Lista paginata con ricerca live HTMX
- CRUD completo: create, edit, deactivate, reactivate (soft-delete)

### Componenti — solo equivalenti, niente quantità assolute nel template
La filosofia: il template è la **ricetta** (equivalenti, ruoli, ratio), le quantità
assolute appartengono al Run (Settimana 4). Nel template:
- Equivalenti sono il dato canonico, sempre editabili (tranne il limitante che è fissato a 1.0)
- Un campo "scala (mmol)" in cima alla tabella mostra mmol/g/mL come **anteprima**
  di cosa sarebbe la reazione a quella scala
- Cambiando la scala, tutta la tabella si ricalcola istantaneamente

### Check list reazione
- Sezione dedicata sotto la tabella componenti
- Voci aggiungibili in linea (es. "Anidrificare il pallone", "Inertizzare con Ar")
- Spunta per marcare come fatto
- Riordino con frecce su/giù
- Eliminazione

### Step modulari (la novità più importante)
Ogni step rappresenta un'operazione post-reazione: workup, estrazione, purificazione,
analisi, o altro. Per ciascuno:
- **Tipo** (badge colorato): workup (blu), estrazione (azzurro), purificazione (verde),
  analisi (gialla), altro (grigio)
- **Titolo** editabile
- **Descrizione** testuale libera
- **Riferimento di calcolo** scelto da menu a tendina:
  - default = reagente limitante della reazione principale
  - oppure qualsiasi altro componente (anche prodotto, solvente, ecc.)
- **Componenti propri** con tabella dedicata e ratio flessibili
- **Check list propria** indipendente da quella della reazione
- Riordino degli step con frecce

### Ratio per i componenti degli step
Massima flessibilità con 6 unità diverse:

| Unità | Significato | Esempio |
|-------|-------------|---------|
| `eq` | equivalenti relativi al riferimento | "3 eq di NaCl" |
| `mL/g` | mL per grammo del riferimento | "10 mL di acqua per grammo di crude" |
| `mL/mmol` | mL per mmol del riferimento | "20 mL di EtOAc per mmol di SM" |
| `% v/v` | % volume relativo al volume del riferimento | "5 % v/v di TFA" |
| `mL` | volume assoluto (no ratio) | "30 mL di brine" |
| `g` | massa assoluta (no ratio) | "2 g di Na2SO4" |

L'app calcola automaticamente g/mL/mmol assoluti partendo dalla scala scelta.

### SmilesDrawer 2.x bundlato (191 KB)
- Auto-render di tutti i `<canvas data-smiles="...">`
- Tema chiaro/scuro auto-detect
- Schema di reazione: derivato da componenti o override SMILES esteso

### Sidebar
- Voce **Reazioni** ora attiva

---

## Come applicare

```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-eln-week3.tar.gz -C ~/Projects/
source .venv/bin/activate
pip install -e ".[dev]"
```

### Schema database

Il modello aggiunge **3 tabelle nuove** (`reaction`, `reaction_component`,
`reaction_step`, `reaction_step_component`, `checklist_item`) rispetto alla Settimana 2.

Visto che non hai ancora applicato la Settimana 3 (la stavi testando), basta:

```bash
python scripts/init_db.py --reset
```

⚠ `--reset` cancella tutti gli utenti/sostanze/lotti. Se vuoi preservare i dati
esistenti, salta `--reset` e usa solo `python scripts/init_db.py`.

### Compila traduzioni e avvia

```bash
pybabel compile -d stoic_eln/translations
make run
```

Cmd+Shift+R nel browser per hard reload.

---

## Cosa testare

### Reazione + scala
1. Sidebar → **Reazioni** → **+ Nuova reazione**
2. Compila titolo "Test Suzuki", T=80°C, atmosfera N2 → salva
3. Detail page: codice tipo `RX-2026-0001`
4. **+ Aggiungi componente** dal modale: Ethanol come SM → diventa limitante (eq=1.0)
5. Cambia "Scala (mmol)" da 1.0 a 10.0 → la riga si aggiorna a 10 mmol, 0.46 g, 0.58 mL

### Più componenti
6. Aggiungi un altro reagente con eq=2.0 → mmol auto = 20 (alla scala 10)
7. Cambia la scala a 50 → tutti i numeri si moltiplicano per 5

### Check list reazione
8. Sezione "Check list reazione" → aggiungi:
   - "Anidrificare il pallone"
   - "Inertizzare con Ar"
   - "Pesare il SM sotto cappa"
9. Spunta una voce → si barra
10. Frecce su/giù riordinano

### Step di workup
11. **+ Aggiungi step** → titolo "Workup acquoso", tipo "Workup",
    descrizione "Spegnere con NH4Cl saturo, estrarre con EtOAc"
12. Card del workup con bordo blu compare
13. Riferimento per i ratio: lascia "Reagente limitante" (default)
14. **Aggiungi componente** allo step (modale dedicato):
    - Water, ruolo Solvente, ratio=10, unità `mL/g`
    - Ethyl acetate, ruolo Solvente, ratio=20, unità `mL/mmol`
15. Le colonne g/mL/mmol mostrano valori calcolati alla scala corrente
16. Cambia il riferimento dal menu (es. su un prodotto) → i valori si ricalcolano

### Check list step
17. Nella card del workup, aggiungi voci alla check list propria:
    - "Separare le fasi"
    - "Lavare con brine"
    - "Anidrificare su Na2SO4"

### Più step
18. **+ Aggiungi step** → "Cromatografia su silice", tipo Purificazione →
    seconda card con bordo verde
19. Frecce su/giù sugli step riordinano l'intera card

### Schema disegnato
20. Aggiungi un prodotto come ruolo "Prodotto" → schema in alto si popola
    automaticamente con freccia A.B>C>D
21. Toggle tema scuro/chiaro → schema si ridisegna nei colori giusti

---

## Cosa non c'è ancora

- **Run** di esecuzione (Settimana 4): ogni reazione potrà avere multipli Run con
  scala specifica, operatore, data, yield reale, e check list con stati indipendenti
  per ciascun Run
- **Auto-deduzione inventario** (Settimana 4): consumare un componente in un Run
  scala automaticamente i grammi/mL dal lotto
- **Drag-and-drop** per il riordino (per ora frecce su/giù)
- **Sicurezza aggregata** della reazione/step (somma pittogrammi GHS dei componenti)

---

## Test

```bash
make test   # 92 test totali (15 W1 + 35 W2 + 42 W3)
```

---

Quando hai testato, mandami uno screenshot di una reazione completa (componenti +
check list reazione + uno step di workup con suoi componenti calcolati). Poi
**Settimana 4**: Run + auto-deduct inventario + yield.
