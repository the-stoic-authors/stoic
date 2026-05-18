# Patch — Frasi GHS complete (CLP Annex IV)

Aggiunge le P-phrases mancanti (P235, P265, P284, P303, P316, P317, P320, P321,
P340, P353, P354) e altre frasi CLP standard. Da 106 frasi totali a 214.

## Cosa cambia

- **File modificato:** `stoic_eln/seeds/hazard_phrases.py`
- **Effetto:** PubChem import non lascerà più frasi "vuote" senza descrizione

## Come applicare

Da Terminal nella cartella del progetto:

```bash
cd ~/Projects/stoic-eln
tar -xzf ~/Downloads/stoic-eln-week2-phrases-patch.tar.gz
```

Poi attiva il venv e ri-esegui il seed (NON serve --reset, è idempotente):

```bash
source .venv/bin/activate
python scripts/init_db.py
```

Output atteso:

```
Admin user already exists.
Loading seed data...
  hazard_phrases: added=108 skipped=106
  substances: added=0 skipped=31
Done.
```

`added=108` perché aggiunge le 108 frasi nuove. `skipped=106` perché le 106
esistenti non vengono toccate.

## Verifica

Ricarica la pagina della sostanza importata da PubChem (es. Pyrrolidine).
Tutte le frasi P dovrebbero ora avere descrizione completa in italiano.

Non serve riavviare Flask né hard reload del browser — i dati sono nel database
e la pagina li rilegge ad ogni richiesta.
