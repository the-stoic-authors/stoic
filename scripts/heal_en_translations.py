"""Add IT→EN translations for all currently-untranslated strings.

Reads ``stoic_eln/translations/en/LC_MESSAGES/messages.po``,
finds entries where msgstr is empty OR msgstr is still in Italian
(detected heuristically), and applies the EN_FIXES dict below.

Anything not in EN_FIXES is left as-is (so existing good
translations are preserved). After this script, run
``pybabel compile -d stoic_eln/translations``.
"""
from __future__ import annotations

import re
from pathlib import Path


# Italian-source-string → English translation mapping for everything
# that's currently untranslated (empty msgstr) or still in Italian
# (msgstr == msgid where msgid is clearly Italian).
#
# Conventions:
#   * Keep printf-style placeholders (%(name)s, %(d).1f, %%) exactly.
#   * Preserve embedded apostrophes ('Salva') as in the source.
#   * For technical terms (run, lotto, batch, prep), the EN version
#     prefers lab English: "run" stays "run", "lotto" → "batch",
#     "preparazione" → "preparation", "miscela" → "mixture".
#   * Hyphen vs em-dash: keep em-dashes (—) as in IT — they print
#     fine.
EN_FIXES: dict[str, str] = {
    # ── Auth / users ────────────────────────────────────────────
    "La password deve essere lunga almeno 8 caratteri.":
        "Password must be at least 8 characters long.",
    "Il tuo account non è attivo. Contatta un amministratore.":
        "Your account is not active. Contact an administrator.",
    "La password attuale non è corretta.":
        "Current password is not correct.",
    "Utente %(u)s creato. Comunica le credenziali e invitalo a cambiare "
    "la password al primo accesso.":
        "User %(u)s created. Share the credentials and ask them to "
        "change the password on first login.",

    # ── Mixtures / preparations ─────────────────────────────────
    "Miscela reagenti": "Reagent mixture",
    "Non posso disattivare: ci sono lotti attivi (%(n)d)":
        "Cannot deactivate: %(n)d active batches still exist.",
    "Nessun lotto precursore selezionato. Seleziona almeno uno.":
        "No precursor batch selected. Select at least one.",
    "Errore imprevisto durante la preparazione.":
        "Unexpected error during preparation.",
    "Seleziona esattamente una tra Sostanza e Miscela.":
        "Select exactly one between Substance and Mixture.",
    "Miscela": "Mixture",
    "Miscela non trovata.": "Mixture not found.",
    "Miscela creata": "Mixture created",
    "Miscela aggiornata": "Mixture updated",
    "Miscela disattivata": "Mixture deactivated",
    "Nuova miscela": "New mixture",
    "Una miscela rappresenta una preparazione fisica (soluzione, "
    "eluente, tampone) con uno o più componenti. Per la sostanza "
    "pura usa invece il catalogo Sostanze.":
        "A mixture represents a physical preparation (solution, "
        "eluent, buffer) with one or more components. For pure "
        "substances, use the Substances catalog instead.",
    "Soluzione": "Solution",
    "Eluente": "Eluent",
    "Tampone": "Buffer",
    "Descrizione": "Description",
    "Concentrazione principale": "Primary concentration",
    "Solvente principale": "Primary solvent",
    "Sovrascrivi GHS dei componenti": "Override component GHS",
    "Pittogrammi GHS (override)": "GHS pictograms (override)",
    "Frasi H (override, separate da virgola)":
        "H phrases (override, comma-separated)",
    "Frasi P (override, separate da virgola)":
        "P phrases (override, comma-separated)",
    "Quantità target non valida.": "Target quantity not valid.",
    "Preparazione completata: lotto %(code)s":
        "Preparation completed: batch %(code)s",
    "Lotto non trovato.": "Batch not found.",
    "Tipo": "Type",
    "Quantità target": "Target quantity",
    "Quantità residua": "Remaining quantity",
    "Quantità prelevata": "Quantity drawn",
    "(aq)": "(aq)",
    "in": "in",
    "Nessun componente strutturato. Solo etichetta veloce.":
        "No structured components. Quick label only.",
    "foto, CoA, schede": "photos, CoA, datasheets",
    "es. 1.0 per HCl 1N": "e.g. 1.0 for HCl 1N",
    "Acqua, MeOH, …": "Water, MeOH, …",

    # ── Backup / encryption (14.0/14.1/14.2/14.3) ───────────────
    "Backup creato: %(name)s (%(mb).2f MB).":
        "Backup created: %(name)s (%(mb).2f MB).",
    "Backup fallito: %(err)s": "Backup failed: %(err)s",
    "Conferma il ripristino spuntando la casella.":
        "Confirm the restore by ticking the checkbox.",
    "Nome file di backup non valido.": "Invalid backup filename.",
    "Ripristino effettuato da %(name)s. Riavvia l'applicazione perché "
    "le modifiche abbiano effetto.":
        "Restored from %(name)s. Restart the application for changes "
        "to take effect.",
    "Ripristino fallito: %(err)s": "Restore failed: %(err)s",
    "Backup %(name)s eliminato.": "Backup %(name)s deleted.",
    "Impossibile eliminare il backup: %(err)s":
        "Could not delete backup: %(err)s",
    "Configurazione backup salvata. Riavvia l'applicazione per "
    "applicare il nuovo orario allo scheduler.":
        "Backup configuration saved. Restart the application to "
        "apply the new schedule.",
    "Test crittografia fallito: %(err)s. La passphrase non è stata "
    "salvata.":
        "Encryption self-test failed: %(err)s. The passphrase was "
        "not saved.",
    "Passphrase salvata in instance/backup.key. I prossimi backup "
    "saranno cifrati con AES-256-GCM. ATTENZIONE: conserva la "
    "passphrase in un posto sicuro; se la perdi, i backup cifrati "
    "saranno irrecuperabili.":
        "Passphrase saved to instance/backup.key. Future backups "
        "will be encrypted with AES-256-GCM. WARNING: keep the "
        "passphrase in a safe place; if you lose it, encrypted "
        "backups become unrecoverable.",
    "Conferma la disattivazione spuntando la casella.":
        "Confirm deactivation by ticking the checkbox.",
    "Crittografia disattivata. I prossimi backup saranno in chiaro. "
    "I backup cifrati esistenti rimangono cifrati.":
        "Encryption disabled. Future backups will be in plaintext. "
        "Existing encrypted backups remain encrypted.",
    "Sorgente passphrase impostata su '%(s)s'. Il cambio è attivo "
    "dal prossimo riavvio di Stoic.":
        "Passphrase source set to '%(s)s'. The change takes effect "
        "from Stoic's next restart.",
    "Da ora in poi Stoic ti chiederà la passphrase a ogni avvio. Se "
    "hai ancora il file instance/backup.key, considera di eliminarlo "
    "manualmente (altrimenti la sicurezza extra del modo 'prompt' "
    "è inutile).":
        "From now on Stoic will ask for the passphrase at every "
        "startup. If instance/backup.key still exists, consider "
        "deleting it manually (otherwise the extra security of "
        "'prompt' mode is wasted).",
    "Conferma l'eliminazione spuntando la casella.":
        "Confirm deletion by ticking the checkbox.",
    "File instance/backup.key eliminato. La passphrase ora esiste "
    "solo nella tua testa (e in RAM mentre Stoic gira).":
        "File instance/backup.key deleted. The passphrase now lives "
        "only in your head (and in RAM while Stoic is running).",
    "Impossibile eliminare il file: %(err)s":
        "Could not delete file: %(err)s",

    # ── Substance / labels / reports ────────────────────────────
    "Scheda lotto (PDF)": "Batch sheet (PDF)",
    "Sostanza già presente: '%(name)s'":
        "Substance already exists: '%(name)s'",
    "Modifica in corso. Premi 'Salva' per confermare o 'Annulla' per "
    "scartare le modifiche.":
        "Editing in progress. Press 'Save' to confirm or 'Cancel' "
        "to discard changes.",
    "Resa > 100%% (%(p).1f%%): possibile errore di pesata o sale "
    "idrato. Salvato comunque.":
        "Yield > 100%% (%(p).1f%%): possible weighing error or "
        "hydrated salt. Saved anyway.",
    "Si è verificato un errore. Riprova più tardi.":
        "An error occurred. Please try again later.",
    "Densità": "Density",

    # ── Orders ──────────────────────────────────────────────────
    "Modifica i dati dell'ordine pianificato. Una volta ordinato non "
    "sarà più modificabile da qui.":
        "Edit the planned order's data. Once placed, it can no "
        "longer be modified from here.",
    "Lascia i valori così se l'ordine è arrivato esattamente come "
    "pianificato. Modifica se è arrivato meno o se il costo finale "
    "è diverso.":
        "Leave values as-is if the order arrived exactly as "
        "planned. Edit if less arrived or if the final cost is "
        "different.",
    "Nessuna voce.": "No items.",

    # ── Runs / reactions ────────────────────────────────────────
    "A-Z, 0-9, trattini. Max 8 caratteri. Nessun punto: la versione "
    "(.1, .2, ...) viene aggiunta automaticamente al salvataggio.":
        "A-Z, 0-9, hyphens. Max 8 characters. No dot: the version "
        "(.1, .2, ...) is appended automatically on save.",
    "Imposta scala, scegli i lotti, inserisci i pesi reali, poi "
    "premi 'Avvia esecuzione'.":
        "Set scale, pick batches, enter real weights, then press "
        "'Start execution'.",
    "Nessun dato di procedimento nel template.":
        "No procedure data in the template.",
    "Run in esecuzione: solo i pesi dei prodotti possono ancora "
    "essere inseriti.":
        "Run in progress: only product weights can still be entered.",

    # ── Attachments (general fallbacks) ─────────────────────────
    "Allegati": "Attachments",
    "Allegato caricato.": "Attachment uploaded.",
    "Nessun allegato. Carica il primo qui sotto.":
        "No attachments yet. Upload the first one below.",
    "caricato da": "uploaded by",
    "Scarica": "Download",
    "Elimina": "Delete",
    "Carica": "Upload",
    "Eliminare definitivamente \"%(f)s\"?":
        "Permanently delete \"%(f)s\"?",
    "Didascalia opzionale (es. NMR purificato)":
        "Optional caption (e.g. purified NMR)",
    "Massimo 100 MB. Tipi accettati: PDF, immagini, dati di "
    "laboratorio (csv, xlsx, jdx, mol, raw, mzML…), archivi (.zip).":
        "Max 100 MB. Allowed: PDF, images, lab data files "
        "(csv, xlsx, jdx, mol, raw, mzML…), archives (.zip).",
    "NMR, HPLC, foto, dati strumentali":
        "NMR, HPLC, photos, instrument data",
    "schede tecniche, protocolli, riferimenti":
        "datasheets, protocols, references",
    "scheda di sicurezza, certificato d'analisi":
        "safety datasheet, certificate of analysis",
    "CoA, scheda lotto, etichetta…": "CoA, batch sheet, label…",
    "CoA del lotto, foto della preparazione, calibrazioni":
        "batch CoA, prep photos, calibrations",
    "(utente eliminato)": "(deleted user)",

    # ── Mixture form helpers and labels ─────────────────────────
    "Opzionale, mostrato sull'etichetta come '(aq)' ecc.":
        "Optional, shown on the label as '(aq)' etc.",
    "Lascia vuoto per un'etichetta veloce (es. HCl 1N senza "
    "tracciare la composizione esatta).":
        "Leave empty for a quick label (e.g. HCl 1N without "
        "tracking the exact composition).",
    "Spunta per definire pittogrammi e frasi specifici per questa "
    "miscela (es. soluzione molto diluita).":
        "Tick to set pictograms and phrases specific to this "
        "mixture (e.g. a very dilute solution).",
    "Stoic scalerà i lotti precursori e creerà un nuovo lotto della "
    "miscela target.":
        "Stoic will scale the precursor batches and create a new "
        "batch of the target mixture.",
    "Quanto ne vuoi produrre?": "How much do you want to produce?",
    "Nessun componente strutturato — l'auto-suggest userà solo la "
    "quantità target.":
        "No structured components — auto-suggest will use only the "
        "target quantity.",
    "Target": "Target",
    "di": "of",
    "Lotti precursori da consumare": "Precursor batches to consume",
    "Generato automaticamente in base alle impostazioni; modificalo "
    "se serve.":
        "Auto-generated from settings; edit it if needed.",
    "es. Scaffale B-3": "e.g. Shelf B-3",
    "Vai alle miscele per prepararne una":
        "Go to mixtures to prepare one",
    "Sommario": "Summary",
    "Anno (per sequenza)": "Year (for sequence)",
    "Lotto non trovato (è stato cancellato dall'inventario?).":
        "Batch not found (was it removed from inventory?).",
    "Tutte le miscele preparate dai precursori, ordinate dalla più "
    "recente.":
        "All mixtures prepared from precursors, newest first.",
    "Codice o nome miscela…": "Batch code or mixture name…",
    "Anno": "Year",
    "ad lib.": "q.s.",
    "mL fissi": "fixed mL",
    "g fissi": "fixed g",
    "Per cromatografie usa una miscela (es. EtOAc/PE 5:2) e "
    "seleziona 'quanto basta' come quantità.":
        "For chromatography use a mixture (e.g. EtOAc/PE 5:2) and "
        "select 'quantum satis' as the quantity.",
    "'quanto basta' (free): la quantità non è specificata nel "
    "template — la registri al Run. Tipico per eluenti di "
    "cromatografia.":
        "'quantum satis' (free): the quantity isn't specified in "
        "the template — you log it at Run time. Typical for "
        "chromatography eluents.",
    "es. 'HCl 1N': il sistema calcolerà le moli dalla "
    "concentrazione × volume.":
        "e.g. 'HCl 1N': the system will compute moles from "
        "concentration × volume.",
    "inserisci": "enter",

    # ── Settings: crypto & backup card / status ─────────────────
    "Crittografia e backup": "Encryption & backups",
    "Snapshot del database compressi e gestiti automaticamente.":
        "Compressed database snapshots, managed automatically.",
    "Cifratura del database, backup automatici notturni, "
    "configurazione di orario e retention, ripristino.":
        "Database encryption, nightly automatic backups, "
        "schedule and retention settings, restore.",

    # ── Live DB encryption (14.2) ───────────────────────────────
    "DB live cifrato (SQLCipher)":
        "Live DB encrypted (SQLCipher)",
    "Il file": "The file",
    "è cifrato a livello di pagina con AES-256-CBC + HMAC-SHA512. "
    "Chi accede al filesystem senza la passphrase vede dati opachi.":
        "is encrypted at the page level with AES-256-CBC + "
        "HMAC-SHA512. Anyone accessing the filesystem without the "
        "passphrase sees opaque data.",
    "(richiede Stoic fermo).": "(requires Stoic to be stopped).",
    "DB live in chiaro": "Live DB in plaintext",
    "Il database del laboratorio è memorizzato in chiaro su disco. "
    "La cifratura dei backup (sopra) protegge i file in":
        "The lab database is stored in plaintext on disk. Backup "
        "encryption (above) protects files in",
    "ma chi ha accesso a": "but anyone with access to",
    "può aprirlo con qualunque client SQLite.":
        "can open it with any SQLite client.",
    "Per attivare la cifratura del DB live serve prima una "
    "passphrase configurata (sezione sotto).":
        "To enable live DB encryption, first configure a passphrase "
        "(section below).",
    "sqlcipher3 non installato.": "sqlcipher3 not installed.",
    "sul terminale di": "on the terminal of",
    "La passphrase è la stessa dei backup, quindi una sola cosa da "
    "ricordare. Il DB live cifrato è protetto contro filesystem "
    "compromessi o accessi non autorizzati al disco.":
        "The passphrase is the same as for backups, so there's "
        "only one thing to remember. The encrypted live DB is "
        "protected against compromised filesystems or unauthorised "
        "disk access.",

    # ── Backup encryption (14.1) UI ─────────────────────────────
    "Crittografia attiva": "Encryption active",
    "I backup vengono cifrati con AES-256-GCM. La passphrase è in":
        "Backups are encrypted with AES-256-GCM. The passphrase "
        "is in",
    "Cambia o disabilita": "Change or disable",
    "Cambiare la passphrase rende illeggibili tutti i backup cifrati "
    "esistenti.":
        "Changing the passphrase makes all existing encrypted "
        "backups unreadable.",
    "Nuova passphrase (min 12 char)": "New passphrase (min 12 chars)",
    "Disabilita: capisco che i prossimi backup saranno in chiaro":
        "Disable: I understand future backups will be in plaintext",
    "Crittografia non attiva": "Encryption not active",
    "I backup sono salvati in chiaro. Per dati di laboratorio "
    "vivamente raccomandato attivare la crittografia: chiunque abbia "
    "accesso a":
        "Backups are saved in plaintext. For lab data, enabling "
        "encryption is strongly recommended: anyone with access to",
    "può leggere il contenuto del database.":
        "can read the database contents.",
    "Conserva la passphrase in un posto sicuro.":
        "Keep the passphrase in a safe place.",
    "Se la perdi, i backup cifrati diventano irrecuperabili. "
    "Anthropic, Stoic e chiunque altro non potrà aiutarti a "
    "recuperarli.":
        "If you lose it, encrypted backups become unrecoverable. "
        "Anthropic, Stoic, and anyone else cannot help you "
        "recover them.",

    # ── Passphrase source (14.3) ────────────────────────────────
    "Sorgente della passphrase": "Passphrase source",
    "Da dove Stoic legge la passphrase quando si avvia. La scelta "
    "determina il livello di protezione contro furto del filesystem.":
        "Where Stoic reads the passphrase from when it starts. "
        "The choice determines the level of protection against "
        "filesystem theft.",
    "Salva (richiede riavvio)": "Save (requires restart)",
    "Hai scelto la modalità 'prompt' (passphrase solo in RAM) ma il "
    "file instance/backup.key esiste ancora su disco. Finché c'è, "
    "chi prende il filesystem può estrarla. Eliminalo per attivare "
    "davvero il modo passphrase-only.":
        "You chose 'prompt' mode (passphrase in RAM only) but the "
        "file instance/backup.key still exists on disk. As long as "
        "it does, whoever takes the filesystem can extract it. "
        "Delete it to truly enable passphrase-only mode.",
    "Confermo: ho memorizzato la passphrase, posso eliminare il file":
        "I confirm: I've memorised the passphrase, the file can be "
        "deleted",
    "Elimina instance/backup.key": "Delete instance/backup.key",

    # ── Backup scheduling and existing backups ──────────────────
    "Backup automatici attivi": "Automatic backups active",
    "Ora (UTC)": "Hour (UTC)",
    "Minuto": "Minute",
    "Conserva ultimi (giorni)": "Keep last (days)",
    "+ uno a settimana per (settimane)":
        "+ one per week for (weeks)",
    ", o assoluta.": ", or absolute.",
    "Esegui backup ora": "Run backup now",
    "Forza un backup immediato e applica la retention configurata.":
        "Force an immediate backup and apply the configured "
        "retention.",
    "Backup esistenti": "Existing backups",
    "Cifrato AES-256-GCM": "Encrypted AES-256-GCM",
    "Ripristina": "Restore",
    "Ripristina backup": "Restore backup",
    "Stai per sostituire il database attuale con il backup:":
        "You are about to replace the current database with the "
        "backup:",
    "Verrà prima creato un backup di sicurezza del DB attuale "
    "(pre-restore), e il file della live DB verrà rinominato con "
    "suffisso":
        "A safety backup of the current DB will be created first "
        "(pre-restore), and the live DB file will be renamed with "
        "the suffix",
    " così non perdi nulla irreversibilmente.":
        " so nothing is lost irreversibly.",
    "Dopo il ripristino devi riavviare Stoic perché le modifiche "
    "abbiano effetto.":
        "After the restore you need to restart Stoic for the "
        "changes to take effect.",
    "Sì, ripristina questo backup": "Yes, restore this backup",

    # ── Prep code template hints ────────────────────────────────
    "slug del nome miscela (es. HCl 6N → HCL6N, max 16 caratteri)":
        "slug of the mixture name (e.g. HCl 6N → HCL6N, max 16 chars)",
    "Esempio: HCL6N-2026-001, HCL1N-2026-002, ELUENTEA-2026-003.":
        "Example: HCL6N-2026-001, HCL1N-2026-002, ELUENTEA-2026-003.",
    "Esempio: HCL6N-2026-001, HCL6N-2026-002, HCL1N-2026-001.":
        "Example: HCL6N-2026-001, HCL6N-2026-002, HCL1N-2026-001.",
    "Struttura": "Structure",

    # ── Cognates that look identical but need explicit override ──
    # to silence the "msgstr==msgid" audit. These are the long
    # untranslated Italian sentences I had missed above.
    "Password aggiornata correttamente.":
        "Password updated successfully.",
    "Il titolo dello step è obbligatorio.":
        "The step title is required.",
    "Solvente (dosato in mL)": "Solvent (dispensed in mL)",
    "Rilevamento automatico": "Auto-detected",
    "Esiste già una sostanza con questo InChIKey: %(name)s":
        "A substance with this InChIKey already exists: %(name)s",
    "InChIKey già usato dalla sostanza '%(name)s'":
        "InChIKey already used by substance '%(name)s'",
    "Tema": "Theme",
    "Chiaro": "Light",
    "Scuro": "Dark",
    "La nuova password deve essere lunga almeno 8 caratteri.":
        "The new password must be at least 8 characters long.",
    "La pagina che stai cercando non esiste.":
        "The page you are looking for does not exist.",
    "Torna alla home": "Back to home",
    "Compila la coppia coerente con lo stato fisico (g per solidi, "
    "mL per liquidi).":
        "Fill the pair consistent with the physical state (g for "
        "solids, mL for liquids).",
    "Lascia vuoto per usare la quantità iniziale.":
        "Leave empty to use the initial quantity.",
    "In stock": "In stock",
    "Aggiungi un commento… (markdown leggero: **grassetto**, "
    "*corsivo*, `codice`, [link](url), - lista)":
        "Add a comment… (light markdown: **bold**, *italic*, "
        "`code`, [link](url), - list)",
    "Consegna prevista:": "Expected delivery:",
    "Sigma-Aldrich, TCI, …": "Sigma-Aldrich, TCI, …",
    "la quantità suggerita è soglia + 50%% di buffer. Il fornitore "
    "e il costo stimato vengono dall'ultimo lotto acquistato. "
    "Verifica e personalizza prima di confermare l'ordine.":
        "the suggested quantity is the threshold + 50%% buffer. "
        "Supplier and estimated cost come from the last batch "
        "purchased. Review and customise before confirming the "
        "order.",
    "(senza SMILES)": "(without SMILES)",
    "SMILES generato": "SMILES generated",
    "Sintassi SMILES estesa: SM1.SM2>reagenti>prodotti oppure "
    "SM>>prodotto. Lasciare vuoto per derivazione automatica.":
        "Extended SMILES syntax: SM1.SM2>reagents>products or "
        "SM>>product. Leave empty for automatic derivation.",
    "Workup": "Workup",
    "Check list": "Checklist",
    "es. Spegnere con NH4Cl saturo, separare le fasi, estrarre la "
    "fase acquosa con EtOAc x 3, riunire le fasi organiche, lavare "
    "con brine, anidrificare su Na2SO4 e concentrare a secco.":
        "e.g. Quench with sat. NH4Cl, separate the phases, extract "
        "the aqueous phase with EtOAc × 3, combine the organic "
        "phases, wash with brine, dry over Na2SO4 and concentrate "
        "to dryness.",
    "Le modifiche non sono visibili agli altri finché non premi "
    "'Pubblica' in fondo alla pagina.":
        "Changes are not visible to others until you press "
        "'Publish' at the bottom of the page.",
    "Temp. (°C)": "Temp. (°C)",
    "es. Sciogliere il SM in DCM anidro sotto Ar, raffreddare a 0 "
    "°C, aggiungere il reagente goccia a goccia, lasciare 12 h a "
    "temperatura ambiente.":
        "e.g. Dissolve the SM in anhydrous DCM under Ar, cool to "
        "0 °C, add the reagent dropwise, leave for 12 h at room "
        "temperature.",
    "range:": "range:",
    "Trend": "Trend",
    "Se non specificato, lo schema viene derivato automaticamente "
    "dai componenti.":
        "If not specified, the scheme is derived automatically "
        "from the components.",
    "Dopo aver salvato la reazione, potrai aggiungere i componenti "
    "(sostanze + ruoli + stechiometria) dalla pagina di dettaglio.":
        "After saving the reaction, you can add components "
        "(substances + roles + stoichiometry) from the detail "
        "page.",
    "Cerca per codice, titolo, sostanza, CAS, fonte…":
        "Search by code, title, substance, CAS, source…",
    "Template:": "Template:",
    "Inventario aggiornato. Spunta le voci della check list e "
    "completa al termine.":
        "Inventory updated. Tick the checklist items and finish "
        "when done.",
    "Template": "Template",
    "Costo totale per arrivare al prodotto, inclusi gli intermedi "
    "sintetizzati internamente":
        "Total cost to reach the product, including internally "
        "synthesised intermediates",
    "Costo materiali non disponibile: nessun lotto assegnato ai "
    "componenti, oppure i lotti non hanno prezzo registrato.":
        "Materials cost not available: no batches assigned to "
        "components, or the batches have no recorded price.",
    "Se procedi, il run sarà registrato come <strong>fallito</strong> "
    "(resa zero) e nessun prodotto verrà aggiunto all'inventario.":
        "If you proceed, the run will be logged as "
        "<strong>failed</strong> (zero yield) and no product will "
        "be added to inventory.",
    "La valuta del laboratorio: usata per tutti i costi (lotti, "
    "ordini, run, statistiche).":
        "The lab's currency: used for all costs (batches, orders, "
        "runs, statistics).",
    "Il codice deve essere ISO 4217 a 3 lettere (es. EUR, USD, "
    "JPY, UZS, ZMW…). Per le valute con simbolo riconosciuto verrà "
    "mostrato il simbolo (€, $, £, ¥, ₹…), altrimenti il codice "
    "stesso.":
        "The code must be ISO 4217 (3 letters: EUR, USD, JPY, "
        "UZS, ZMW…). For currencies with a recognised symbol, the "
        "symbol is shown (€, $, £, ¥, ₹…); otherwise the code "
        "itself.",
    "Stoic non ha self-signup: gli utenti vengono creati qui da un "
    "amministratore. Comunica username e password all'utente, che "
    "potrà cambiarla dopo il primo accesso in Profilo → Cambia "
    "password.":
        "Stoic has no self-signup: users are created here by an "
        "administrator. Share the username and password with the "
        "user, who can change it after first login at Profile → "
        "Change password.",
    "Utente: esegue run, non modifica template. Supervisore: crea/"
    "modifica reazioni e sostanze. Amministratore: tutto.":
        "User: runs experiments, doesn't modify templates. "
        "Supervisor: creates/edits reactions and substances. "
        "Administrator: everything.",
    "Default:": "Default:",
    "Per template": "Per template",
    "può creare, modificare ed eliminare reazioni e sostanze. Non "
    "può gestire utenti, impostazioni o audit log.":
        "can create, edit and delete reactions and substances. "
        "Cannot manage users, settings or the audit log.",
    "Non puoi cambiare il tuo ruolo. Per creare un nuovo utente, "
    "usa il bottone in alto a destra.":
        "You can't change your own role. To create a new user, "
        "use the button in the top-right.",
    "Questa sostanza è disattivata. Non può essere usata in nuove "
    "reazioni, ma i run storici la mantengono visibile.":
        "This substance is deactivated. It cannot be used in new "
        "reactions, but historical runs keep it visible.",
    "Proprietà fisiche": "Physical properties",
    "Costo/unità": "Cost/unit",
    "Sotto questa quantità totale la sostanza apparirà negli avvisi "
    "della Dashboard.":
        "Below this total quantity the substance will appear in "
        "Dashboard alerts.",
    "Questa sostanza esiste già nel catalogo:":
        "This substance already exists in the catalog:",
    "Proprietà": "Properties",
    "Dati incompleti? Dopo l'import puoi modificare la sostanza "
    "per aggiungere campi mancanti.":
        "Incomplete data? After import you can edit the substance "
        "to add missing fields.",
    "Cerca per nome, IUPAC, CAS, formula, lotto…":
        "Search by name, IUPAC, CAS, formula, batch…",
    "Documento generato automaticamente. Verificare sempre la SDS "
    "ufficiale del fornitore prima dell'uso.":
        "Automatically generated document. Always check the "
        "supplier's official SDS before use.",
}


def parse_blocks(text: str) -> list[str]:
    """Split a .po file into entry blocks (separated by blank lines)."""
    return re.split(r"\n\n", text)


def extract_msgid(block: str) -> str | None:
    pattern = r'^msgid (".*"(?:\s*\n".*")*)'
    m = re.search(pattern, block, re.MULTILINE)
    if not m:
        return None
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    return "".join(p.replace('\\"', '"').replace("\\\\", "\\")
                   .replace("\\n", "\n").replace("\\t", "\t")
                   for p in parts)


def extract_msgstr(block: str) -> str | None:
    pattern = r'^msgstr (".*"(?:\s*\n".*")*)'
    m = re.search(pattern, block, re.MULTILINE)
    if not m:
        return None
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    return "".join(p.replace('\\"', '"').replace("\\\\", "\\")
                   .replace("\\n", "\n").replace("\\t", "\t")
                   for p in parts)


def encode_po_string(s: str) -> str:
    escaped = (s.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\t", "\\t"))
    if "\n" not in escaped:
        return f'"{escaped}"'
    lines = escaped.split("\n")
    out = ['""']
    for line in lines[:-1]:
        out.append(f'"{line}\\n"')
    if lines[-1]:
        out.append(f'"{lines[-1]}"')
    return "\n".join(out)


def replace_msgstr(block: str, new_literal: str) -> str:
    pattern = r'^msgstr (".*"(?:\s*\n".*")*)'
    return re.sub(pattern, f"msgstr {new_literal}", block,
                  count=1, flags=re.MULTILINE)


def drop_fuzzy(block: str) -> str:
    out = []
    for line in block.split("\n"):
        if line.startswith("#,"):
            flags = [f.strip() for f in line[2:].split(",")]
            flags = [f for f in flags if f and f != "fuzzy"]
            if flags:
                out.append("#, " + ", ".join(flags))
        else:
            out.append(line)
    return "\n".join(out)


def main() -> None:
    po = Path("stoic_eln/translations/en/LC_MESSAGES/messages.po")
    text = po.read_text(encoding="utf-8")
    blocks = parse_blocks(text)

    applied = 0
    missing: list[str] = []
    new_blocks = []
    for i, block in enumerate(blocks):
        if i == 0:
            new_blocks.append(block)
            continue
        if block.strip().startswith("#~"):
            new_blocks.append(block)
            continue
        if "msgid " not in block or "msgstr " not in block:
            new_blocks.append(block)
            continue
        msgid = extract_msgid(block)
        msgstr = extract_msgstr(block)
        if msgid is None or msgstr is None:
            new_blocks.append(block)
            continue
        if msgid in EN_FIXES:
            translation = EN_FIXES[msgid]
            block = replace_msgstr(block, encode_po_string(translation))
            block = drop_fuzzy(block)
            applied += 1
        elif msgstr == "":
            missing.append(msgid)
        new_blocks.append(block)

    out = "\n\n".join(new_blocks)
    if not out.endswith("\n"):
        out += "\n"
    po.write_text(out, encoding="utf-8")

    print(f"Applied: {applied} EN translations.")
    if missing:
        print(f"\nStill empty (not in EN_FIXES): {len(missing)}")
        for m in missing:
            print(f"  {m!r}")


if __name__ == "__main__":
    main()
