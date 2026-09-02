# Patch v1.5.1 — la composizione si dichiara, non si calcola

Correzione di un difetto di v1.5.0 emerso alla prima prova su un run
vero, più il cambio di design che ne è seguito.

## Il bug

Su uno step senza quantità reali registrate, la sezione *Solvente
recuperato* non compariva affatto. Causa: `recoverable_components()`
scartava i componenti privi di volume, e il template nasconde la
sezione quando la lista è vuota. Nessun messaggio: solo assenza.

Due errori distinti, uno di logica e uno di UX:

1. **Il volume serviva solo a calcolare una composizione v/v**, quindi
   è irrilevante quando si recupera da un unico componente — quella è
   quella sostanza al 100%, numeri o non numeri. Il requisito del caso
   multi-componente era stato imposto anche al caso singolo.
2. **Sparire in silenzio è la peggiore delle risposte.** Anche quando
   manca davvero qualcosa, va detto cosa manca.

### Nota sui test di v1.5.0

Passavano tutti perché ogni test inseriva i volumi prima di registrare.
Uno di essi asseriva `recoverable_components(step) == []` a quantità
mancanti: documentava il comportamento sbagliato come se fosse il
contratto. Le mutazioni non l'avevano preso perché verificavano il
calcolo della composizione, non il presupposto per arrivarci.

## Il cambio di design

Pretendere i volumi per calcolare la composizione sarebbe stata **falsa
precisione**. Il recupero non è proporzionale:

- l'esano bolle a 69 °C, l'acetato di etile a 77 °C → il distillato è
  arricchito nel più volatile
- in gradiente la composizione carica cambia lungo la corsa
- spesso si concentrano solo le frazioni che contengono prodotto, non
  tutto l'eluato

Quindi un 20:80 caricato può diventare un 40:60 in bottiglia, e
calcolarlo dai volumi darebbe un numero autorevole a un dato che non lo
è — numero che poi verrebbe riusato in una colonna futura.

**Ora**: la composizione è un campo per componente, pre-riempito col
rapporto caricato quando i volumi ci sono, vuoto quando non ci sono. Il
valore dell'operatore vince sempre. Il calcolo non è un canale
parallelo, è il default di un campo unico.

Limite dichiarato: la stima resta a occhio, salvo misura vera (indice
di rifrazione, GC). Il campo registra il giudizio del chimico, non lo
trasforma in misura — e l'arrotondamento al 10% serve anche a non far
sembrare misurato ciò che è stimato.

## Cosa cambia

- `recoverable_components()` non filtra più sui volumi
- `suggested_percentages()` (nuova) — il suggerimento, o `None`
- `register_recovery(..., percentages=...)` — un componente → 100%
  automatico; più componenti → percentuali dichiarate, con fallback sul
  rapporto caricato e rifiuto esplicito se mancano entrambi
- Percentuali normalizzate prima dell'arrotondamento
- Form: un campo `%` per componente accanto alla checkbox

## Test

31 in totale (22 di v1.5.0 + 9 nuovi), fra cui il test di regressione
che rende la sezione **senza** quantità registrate.

Validazione per mutazione: ripristinando il filtro sui volumi cadono 5
test; ignorando le percentuali dichiarate ne cadono 2.

## Lezione operativa

La prima esecuzione della mutazione "ripristina il filtro sui volumi"
non aveva fatto fallire nulla — perché lo script `replace` non trovava
il testo (il file era stato riformattato) e quindi **non mutava
niente**. Una mutazione che non muta produce un verde finto, cioè
esattamente ciò che la tecnica dovrebbe smascherare.

Da qui in avanti: ogni mutazione va scritta con `assert old in source`
prima della sostituzione.

## Migrazione

Nessuna: v1.5.1 non tocca lo schema. Se v1.5.0 è già stata applicata,
`flask migrate-solvent-recovery` è già stato eseguito e non serve
rifarlo.
