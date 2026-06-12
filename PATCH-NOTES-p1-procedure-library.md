# Stoic ELN — P1: Libreria procedure riutilizzabili

Prima delle tre patch della feature "procedure standard" (P1
libreria, P2 schede speciali + cromatografia, P3 estrazione /
ricristallizzazione / distillazione + PDF).

## Cosa fa

Una **libreria globale del laboratorio** di step riutilizzabili
("Procedure", nuova voce nel menu). Flusso:

  - **Creare**: in un protocollo draft, ogni step card ha un nuovo
    bottone 📚 ("Salva nella libreria") → nome + flag sovrascrivi.
    Componenti e checklist vengono copiati nel template.
  - **Usare**: nel modal "Nuovo passo" di un protocollo draft, se
    la libreria non è vuota appare "…oppure inserisci dalla
    libreria" con un select. L'inserimento COPIA il template come
    step normale in coda.
  - **Gestire**: pagina /procedures con card per ogni template
    (componenti e checklist visibili), rinomina inline, elimina
    con conferma.

## Decisione di design: copia, non riferimento

Inserire un template COPIA le righe. Modificare la libreria non
riscrive mai i protocolli esistenti (stessa filosofia dello
snapshot Run→Reaction). Il test
`test_insert_template_into_reaction_deep_copies` verifica che
mutare lo step inserito non tocchi il template, e
`test_deleting_template_does_not_touch_protocol_steps` che
eliminare dalla libreria non tocchi i protocolli.

L'editing dei template avviene attraverso i protocolli (inserisci
→ modifica → ri-salva con sovrascrivi): l'editor completo degli
step esiste già lì, duplicarlo nella libreria sarebbe stato solo
superficie di manutenzione in più.

## File

Nuovi: `models/step_template.py` (StepTemplate,
StepTemplateComponent, StepTemplateChecklistItem),
`blueprints/procedures/` (5 route), `templates/procedures/index.html`,
`tests/test_procedure_library.py` (6 test).

Modificati: `models/__init__.py`, `stoic_eln/__init__.py`
(registrazione blueprint), `blueprints/reactions/routes.py` (passa
i template alla detail in draft), `templates/reactions/_step_card.html`
(bottone + form salva), `templates/reactions/detail.html` (select
inserisci nel modal), `templates/base.html` (nav), `.po` EN
(20 stringhe nuove, 1 duplicato evitato).

## Applicazione

```
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-p1-procedure-library.tar.gz -C ~/Projects/

# NUOVE TABELLE: step_template, step_template_component,
# step_template_checklist_item
export FLASK_APP=stoic_eln
make ensure-schema

# Ricompila le traduzioni
make translations

make test 2>&1 | tail -3
```

Atteso: **635 passed** (629 + 6).

Verifica visiva rapida: `make run` → menu "Procedure" (vuota) →
apri un protocollo draft con step → icona libreria sulla step
card → salva → torna in Procedure → la vedi → in un altro
protocollo draft, "Nuovo passo" → inserisci dalla libreria.

## Prossime

P2: `procedure_type` + `procedure_params` su ReactionStep/RunStep,
servizio calcoli, scheda cromatografia (Still: ΔRf→silice,
diametro colonna, eluente, gradiente registrabile). P3: estrazione,
ricristallizzazione, distillazione, PDF.
