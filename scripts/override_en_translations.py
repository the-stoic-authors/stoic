"""Translation override pass for EN.

Earlier passes left many wrong translations from `pybabel update`
fuzzy match heuristics. This script does a *forceful* rewrite of
EN translations using the dict below, which was reviewed
page-by-page against the actual UI.

Run after ``pybabel update``. Compile .mo after.
"""
from __future__ import annotations

import re
from pathlib import Path


# Each entry is an explicit, manually-verified IT → EN translation.
# Many of these overwrite WRONG translations that earlier passes left
# in place (e.g. Miscele → SMILES, Densità → Quantity).
#
# Organised by UI area for maintainability. Every entry here is
# authoritative: the script always replaces the current msgstr with
# the EN value below.
OVERRIDES: dict[str, str] = {
    # ── Sidebar / base layout ───────────────────────────────────
    "Laboratorio": "Laboratory",
    "Dashboard": "Dashboard",
    "Sostanze": "Substances",
    "Reazioni": "Reactions",
    "Storico run": "Runs history",
    "Miscele": "Mixtures",
    "Storico preparazioni": "Preparations history",
    "Magazzino": "Storage",
    "Inventario": "Inventory",
    "Ordini": "Orders",
    "Admin": "Admin",
    "Utenti": "Users",
    "Report (in arrivo)": "Reports (coming soon)",
    "Report": "Reports",
    "Audit log": "Audit log",
    "Impostazioni": "Settings",
    "Mostra/nascondi sidebar": "Show/hide sidebar",
    "Tema": "Theme",
    "Chiaro": "Light",
    "Scuro": "Dark",
    "Profilo": "Profile",
    "Logout": "Logout",

    # ── Auth / login / password ─────────────────────────────────
    "Username": "Username",
    "Password": "Password",
    "Password attuale": "Current password",
    "Nuova password": "New password",
    "Conferma nuova password": "Confirm new password",
    "Cambia password": "Change password",
    "Le password non coincidono.": "Passwords do not match.",
    "Username o password non corretti.": "Incorrect username or password.",
    "Sei stato disconnesso.": "You have been logged out.",
    "La password attuale non è corretta.":
        "Current password is not correct.",
    "La password deve essere lunga almeno 8 caratteri.":
        "Password must be at least 8 characters long.",
    "La nuova password deve essere lunga almeno 8 caratteri.":
        "The new password must be at least 8 characters long.",
    "Il tuo account non è attivo. Contatta un amministratore.":
        "Your account is not active. Contact an administrator.",
    "Password aggiornata correttamente.":
        "Password updated successfully.",
    "Ricordami": "Remember me",
    "Accedi": "Log in",

    # ── Dashboard ───────────────────────────────────────────────
    "Benvenuto": "Welcome",
    "Lotti attivi": "Active batches",
    "Run completati": "Completed runs",
    "Ordini in arrivo": "Incoming orders",
    "Tutti gli ordini": "All orders",
    "Lotti scaduti": "Expired batches",
    "Lotti in scadenza (≤30 giorni)": "Batches expiring (≤30 days)",
    "consegna prevista:": "expected delivery:",
    "in ritardo di %(d)d gg": "%(d)d days overdue",
    "e altri %(n)d ordini…": "and %(n)d more orders…",
    "e altri %(n)d lotti…": "and %(n)d more batches…",
    "e altre %(n)d sostanze…": "and %(n)d more substances…",
    "vedi tutti": "see all",
    "Apri lista della spesa": "Open shopping list",
    "Attività recente": "Recent activity",
    "Audit completo": "Full audit",
    "da": "by",

    # ── Common buttons & actions ────────────────────────────────
    "Salva": "Save",
    "Annulla": "Cancel",
    "Modifica": "Edit",
    "Elimina": "Delete",
    "Carica": "Upload",
    "Scarica": "Download",
    "Aggiungi": "Add",
    "Rimuovi": "Remove",
    "Cerca": "Search",
    "Indietro": "Back",
    "Tutti": "All",
    "Tutte": "All",
    "Aggiorna": "Update",
    "Apri": "Open",
    "Stampa": "Print",
    "Visualizza": "View",
    "Conferma": "Confirm",
    "Inserisci": "Enter",
    "inserisci": "enter",
    "Sposta su": "Move up",
    "Sposta giù": "Move down",
    "Aggiornata": "Updated",
    "Aggiornato": "Updated",
    "Disattiva": "Deactivate",
    "Disattivati": "Inactive",
    "Disattivate": "Inactive",
    "Mostra disattivate": "Show inactive",
    "Mostra disattivati": "Show inactive",
    "Attiva": "Activate",
    "Pulisci filtri": "Clear filters",
    "Qualsiasi": "Any",
    "Sì, ripristina questo backup": "Yes, restore this backup",
    "Anteprima": "Preview",
    "Anteprima:": "Preview:",
    "Anteprima import": "Import preview",
    "Esempi": "Examples",
    "Pubblica": "Publish",
    "Esegui": "Run",
    "Esegui:": "Run:",
    "Esegui backup ora": "Run backup now",
    "Vai": "Go",
    "Continua": "Continue",
    "Esci": "Exit",
    "Avanti": "Next",
    "Precedente": "Previous",
    "tutti": "all",
    "tutte": "all",
    "di": "of",
    "oppure": "or",

    # ── Substances list / detail / form ─────────────────────────
    "Catalogo sostanze": "Substance catalog",
    "Nuova sostanza": "New substance",
    "Cerca sostanza…": "Search substance…",
    "Cerca per nome, IUPAC, CAS, formula, lotto…":
        "Search by name, IUPAC, CAS, formula, batch…",
    "Modifica sostanza": "Edit substance",
    "Disattiva sostanza": "Deactivate substance",
    "Riattiva sostanza": "Reactivate substance",
    "Disattivata": "Deactivated",
    "Disattivato": "Deactivated",
    "Sostanza non trovata.": "Substance not found.",
    "Sostanza creata.": "Substance created.",
    "Sostanza aggiornata.": "Substance updated.",
    "Sostanza disattivata.": "Substance deactivated.",
    "Sostanza riattivata.": "Substance reactivated.",
    "Nome": "Name",
    "Nome IUPAC": "IUPAC name",
    "IUPAC": "IUPAC",
    "Numero CAS": "CAS number",
    "Formula": "Formula",
    "Peso molecolare": "Molecular weight",
    "Peso molecolare (g/mol)": "Molecular weight (g/mol)",
    "Densità": "Density",
    "Densità (g/mL)": "Density (g/mL)",
    "Densità:": "Density:",
    "Stato fisico": "Physical state",
    "Punto di fusione": "Melting point",
    "Punto di fusione (°C)": "Melting point (°C)",
    "Punto di ebollizione": "Boiling point",
    "Punto di ebollizione (°C)": "Boiling point (°C)",
    "SMILES": "SMILES",
    "InChI": "InChI",
    "InChIKey": "InChIKey",
    "PubChem CID": "PubChem CID",
    "Cerca su PubChem": "Search on PubChem",
    "Risultato PubChem": "PubChem result",
    "Errore PubChem: %(err)s": "PubChem error: %(err)s",
    "Errore: %(err)s": "Error: %(err)s",
    "Importa da PubChem": "Import from PubChem",
    "Cerca un altro composto": "Search another compound",
    "Esempi di ricerca": "Search examples",
    "Pericoli e classificazione GHS":
        "Hazards and GHS classification",
    "Indicazioni di pericolo (Frasi H)":
        "Hazard statements (H phrases)",
    "Consigli di prudenza (Frasi P)":
        "Precautionary statements (P phrases)",
    "Pittogrammi GHS": "GHS pictograms",
    "Pittogrammi GHS:": "GHS pictograms:",
    "Pittogrammi GHS (override)": "GHS pictograms (override)",
    "Frasi H": "H phrases",
    "Frasi P": "P phrases",
    "Frasi H:": "H phrases:",
    "Frasi P:": "P phrases:",
    "FRASI H": "H PHRASES",
    "FRASI P": "P PHRASES",
    "Frasi H (separate da virgola)": "H phrases (comma-separated)",
    "Frasi P (separate da virgola)": "P phrases (comma-separated)",
    "Frasi H (override, separate da virgola)":
        "H phrases (override, comma-separated)",
    "Frasi P (override, separate da virgola)":
        "P phrases (override, comma-separated)",
    "Sovrascrivi GHS dei componenti":
        "Override component GHS",
    "Proprietà": "Properties",
    "Proprietà fisiche": "Physical properties",
    "Rilevamento automatico": "Auto-detected",
    "(senza SMILES)": "(without SMILES)",
    "SMILES generato": "Generated SMILES",
    "Stato": "State",
    "Soglia basso stock": "Low-stock threshold",
    "Soglia (g) — per solidi": "Threshold (g) — for solids",
    "Soglia (mL) — per liquidi": "Threshold (mL) — for liquids",
    "sotto soglia": "low stock",
    "Soglie aggiornate.": "Thresholds updated.",
    "Sostanza già presente: '%(name)s'":
        "Substance already exists: '%(name)s'",
    "Questa sostanza esiste già nel catalogo:":
        "This substance already exists in the catalog:",
    "Esiste già una sostanza con questo InChIKey: %(name)s":
        "A substance with this InChIKey already exists: %(name)s",
    "InChIKey già usato dalla sostanza '%(name)s'":
        "InChIKey already used by substance '%(name)s'",
    "Questa sostanza è disattivata. Non può essere usata in nuove "
    "reazioni, ma i run storici la mantengono visibile.":
        "This substance is deactivated. It cannot be used in new "
        "reactions, but historical runs keep it visible.",
    "Torna alla scheda": "Back to details",
    "Torna alle sostanze": "Back to substances",

    # ── Inventory (lots / batches) ──────────────────────────────
    "Codice lotto": "Batch code",
    "Quantità": "Quantity",
    "Quantità iniziale (g)": "Initial quantity (g)",
    "Quantità iniziale (mL)": "Initial quantity (mL)",
    "Quantità residua (g)": "Remaining quantity (g)",
    "Quantità residua (mL)": "Remaining quantity (mL)",
    "Quantità residua": "Remaining quantity",
    "Quantità iniziale": "Initial quantity",
    "Quantità ricevuta": "Received quantity",
    "Quantità ricevuta (g)": "Received quantity (g)",
    "Quantità ricevuta (mL)": "Received quantity (mL)",
    "Quantità ordinata": "Ordered quantity",
    "Quantità suggerita": "Suggested quantity",
    "Quantità target": "Target quantity",
    "Quantità prelevata": "Quantity drawn",
    "Quantità target non valida.": "Invalid target quantity.",
    "Quantità non valida.": "Invalid quantity.",
    "Inserisci una quantità (g o mL).":
        "Enter a quantity (g or mL).",
    "Costo totale": "Total cost",
    "Costo totale (EUR)": "Total cost (EUR)",
    "Costo effettivo": "Actual cost",
    "Costo unitario": "Unit cost",
    "Costo/unità": "Cost/unit",
    "Costo di un lotto": "Batch cost",
    "Costo medio": "Avg cost",
    "Costo medio per run": "Avg cost per run",
    "Costo totale per run": "Total cost per run",
    "Costo totale stimato": "Estimated total cost",
    "Costo materiali": "Materials cost",
    "Costo diretto": "Direct cost",
    "Data di acquisto": "Purchase date",
    "Data di scadenza": "Expiry date",
    "Acquistato": "Purchased",
    "Posizione": "Location",
    "Fornitore": "Supplier",
    "Codice catalogo": "Catalog code",
    "Codice fornitore": "Supplier code",
    "Lotto attivo": "Active",
    "Lotti attivi": "Active batches",
    "Lotti scaduti": "Expired batches",
    "Lotti consumati": "Consumed batches",
    "Lotti precursori da consumare": "Precursor batches to consume",
    "Lotto prodotto": "Produced batch",
    "Lotto manuale": "Manual batch",
    "Lotto attivo": "Active batch",
    "Nessun lotto attivo.": "No active batches.",
    "nessun lotto disponibile": "no batch available",
    "Modifica lotto": "Edit batch",
    "Nuovo lotto": "New batch",
    "Prepara nuovo lotto": "Prepare new batch",
    "Apri lotto": "Open batch",
    "Lotto non trovato.": "Batch not found.",
    "Lotto non trovato (è stato cancellato dall'inventario?).":
        "Batch not found (was it removed from inventory?).",
    "Lotto non valido.": "Invalid batch.",
    "Dati del lotto": "Batch details",
    "Tutti": "All",
    "In stock": "In stock",
    "Stock": "Stock",
    "In scadenza (≤30 gg)": "Expiring (≤30 days)",
    "Scaduti": "Expired",
    "Scadenza": "Expiry",
    "Scad": "Exp",
    "scaduto da %(d)d gg": "expired %(d)d days ago",
    "entro %(d)d gg": "in %(d)d days",
    "Totale visualizzato:": "Displayed total:",
    "Sostanze esaurite": "Out-of-stock substances",
    "Sostanze in scadenza": "Expiring substances",

    # ── Labels & batch sheet (PDF) ──────────────────────────────
    "Stampa etichetta": "Print label",
    "Etichetta": "Label",
    "Etichette": "Labels",
    "Formato": "Format",
    "Formato etichetta non valido.": "Invalid label format.",
    "Copie": "Copies",
    "Posizione di partenza sul foglio":
        "Start position on the sheet",
    "Genera PDF": "Generate PDF",
    "Scheda lotto (PDF)": "Batch sheet (PDF)",
    "Struttura": "Structure",
    "Composizione": "Composition",
    "Composizione di": "Composition of",
    "Solvente": "Solvent",
    "Solvente principale": "Primary solvent",
    "Solvente (dosato in mL)": "Solvent (dispensed in mL)",
    "Cosolvente": "Co-solvent",
    "cosolvente": "co-solvent",
    "Concentrazione": "Concentration",
    "Concentrazione principale": "Primary concentration",
    "(aq)": "(aq)",
    "in": "in",

    # ── Mixtures ────────────────────────────────────────────────
    "Miscela": "Mixture",
    "Miscela reagenti": "Reagent mixture",
    "Miscela (soluzione)": "Mixture (solution)",
    "Miscela non trovata.": "Mixture not found.",
    "Miscela creata": "Mixture created",
    "Miscela aggiornata": "Mixture updated",
    "Miscela disattivata": "Mixture deactivated",
    "Modifica miscela": "Edit mixture",
    "Disattiva miscela": "Deactivate mixture",
    "Nuova miscela": "New mixture",
    "Questa miscela è disattivata.": "This mixture is deactivated.",
    "miscela": "mixture",
    "Tipo": "Type",
    "Tipo di componente": "Component type",
    "Soluzione": "Solution",
    "Eluente": "Eluent",
    "Tampone": "Buffer",
    "Altro": "Other",
    "Descrizione": "Description",
    "Componente": "Component",
    "Componenti": "Components",
    "(componente rimosso)": "(component removed)",
    "Acqua, MeOH, …": "Water, MeOH, …",
    "Vai alle miscele per prepararne una":
        "Go to mixtures to prepare one",
    "Preparazione": "Preparation",
    "Preparazioni": "Preparations",
    "Preparazione di": "Preparation of",
    "Codice o nome miscela…": "Batch code or mixture name…",
    "Quanto ne vuoi produrre?": "How much do you want to produce?",
    "Anno": "Year",
    "Anno (per sequenza)": "Year (for sequence)",
    "Numero sequenza": "Sequence number",
    "Preparazione completata: lotto %(code)s":
        "Preparation completed: batch %(code)s",

    # ── Reactions / templates ───────────────────────────────────
    "Reazione": "Reaction",
    "Reazione principale": "Main reaction",
    "Reazione SMILES": "Reaction SMILES",
    "Nuova reazione": "New reaction",
    "Modifica reazione": "Edit reaction",
    "Torna alla reazione": "Back to reaction",
    "Torna al template": "Back to template",
    "Torna alle reazioni": "Back to reactions",
    "Template": "Template",
    "Template:": "Template:",
    "Codice template": "Template code",
    "Tutti i template": "All templates",
    "Template attivi": "Active templates",
    "Statistiche template": "Template statistics",
    "Confronto template": "Template comparison",
    "%(n)d reazioni": "%(n)d reactions",
    "Materiale di partenza (SM)": "Starting material (SM)",
    "Materiale di partenza (limitante)":
        "Starting material (limiting)",
    "Standard interno": "Internal standard",
    "Sottoprodotto": "Byproduct",
    "Reagente": "Reagent",
    "Reagente limitante": "Limiting reagent",
    "Catalizzatore": "Catalyst",
    "Legante": "Ligand",
    "Ossidante": "Oxidant",
    "Riducente": "Reductant",
    "Prodotto": "Product",
    "Schema SMILES (opzionale)": "SMILES scheme (optional)",
    "Schema SMILES manuale (opzionale)":
        "Manual SMILES scheme (optional)",
    "SMILES manuale": "Manual SMILES",
    "Override manuale": "Manual override",
    "Sintassi SMILES estesa:": "Extended SMILES syntax:",
    "Fonte / riferimento": "Source / reference",
    "Fonte": "Source",
    "Ruolo": "Role",
    "Ruolo non valido.": "Invalid role.",
    "Questa reazione non è una bozza.":
        "This reaction is not a draft.",
    "Modifiche scartate.": "Changes discarded.",
    "Dati componente non validi.": "Invalid component data.",
    "Il titolo dello step è obbligatorio.":
        "The step title is required.",
    "Scala non valida.": "Invalid scale.",
    "La scala deve essere maggiore di zero.":
        "Scale must be greater than zero.",
    "Sorgente non valida.": "Invalid source.",
    "Bozza di run eliminata.": "Run draft deleted.",
    "Solo le bozze possono essere annullate.":
        "Only drafts can be cancelled.",
    "Puoi eseguire solo template pubblicati.":
        "Only published templates can be run.",
    "Bozza di run creata: %(code)s.": "Run draft created: %(code)s.",
    "Stai modificando una bozza.": "You are editing a draft.",
    "Stai modificando una bozza pubblicata.":
        "You are editing a published version.",
    "Versioni precedenti": "Previous versions",
    "bozza": "draft",
    "BOZZA": "DRAFT",
    "Il reagente limitante ha sempre eq=1":
        "Limiting reagent always has eq=1",
    "Imposta come limitante": "Set as limiting",
    "Esegui run": "Run reaction",
    "ad lib.": "ad lib.",
    "mL fissi": "fixed mL",
    "g fissi": "fixed g",
    "quanto basta": "ad libitum",
    "Eliminare questa voce?": "Delete this item?",
    "Elimina passo": "Delete step",
    "breve scopo della reazione": "short purpose of the reaction",
    "Per i ruoli non-solventi": "For non-solvent roles",
    "Solo per i solventi": "Only for solvents",
    "Resa": "Yield",
    "Resa:": "Yield:",
    "Resa media": "Average yield",
    "resa media:": "avg yield:",
    "Ultimo run": "Last run",
    "Apri ultimo run": "Open last run",
    "nel tempo (run cronologici)": "over time (chronological runs)",
    "Run completati totali": "Total completed runs",
    "media costo × n. run, per ogni template":
        "avg cost × num runs, per template",
    "medio per run": "avg per run",
    "medio": "avg",
    "ultimo": "latest",
    "del prodotto (cumulativo)": "of product (cumulative)",
    "Tutti i run": "All runs",
    "ordine cronologico": "chronological order",
    "tutti con dati di costo": "all with cost data",

    # ── Run execution ───────────────────────────────────────────
    "Esecuzione di un Run": "Run execution",
    "Avvia esecuzione": "Start execution",
    "Torna a inserire i pesi": "Go back and enter weights",
    "Sì, registra come fallito": "Yes, mark as failed",
    "Resa > 100%% (%(p).1f%%): possibile errore di pesata o sale "
    "idrato. Salvato comunque.":
        "Yield > 100%% (%(p).1f%%): possible weighing error or "
        "hydrated salt. Saved anyway.",
    "scegli lotto…": "pick batch…",
    "libera": "free",
    "Note di esecuzione": "Execution notes",
    "Note post-mortem": "Post-mortem notes",
    "link NMR, lessons learned, ecc.":
        "NMR links, lessons learned, etc.",
    "Avviato:": "Started:",
    "Apri PDF sintetico in una nuova scheda":
        "Open summary PDF in a new tab",
    "Eliminare questa bozza di run?": "Delete this run draft?",
    "Elimina bozza": "Delete draft",
    "Run in esecuzione: solo i pesi dei prodotti possono ancora "
    "essere inseriti.":
        "Run in progress: only product weights can still be entered.",
    "Scegliere la scala (mmol del limitante)":
        "Choose the scale (mmol of the limiting reagent)",
    "del limitante": "of the limiting reagent",
    "dopo l'avvio": "after start",
    "Inventario aggiornato. Spunta le voci della check list e "
    "completa al termine.":
        "Inventory updated. Tick the checklist items and finish "
        "when done.",
    "Imposta scala, scegli i lotti, inserisci i pesi reali, poi "
    "premi 'Avvia esecuzione'.":
        "Set scale, pick batches, enter real weights, then press "
        "'Start execution'.",
    "Workup": "Workup",
    "Check list": "Checklist",
    "Reale": "Actual",
    "Acquistato": "Purchased",
    "Reale": "Actual",
    "Costo totale per arrivare al prodotto, inclusi gli intermedi "
    "sintetizzati internamente":
        "Total cost to reach the product, including internally "
        "synthesised intermediates",
    "Costo materiali non disponibile: nessun lotto assegnato ai "
    "componenti, oppure i lotti non hanno prezzo registrato.":
        "Materials cost not available: no batches assigned to "
        "components, or the batches have no recorded price.",
    "solo materie prime acquistate": "purchased raw materials only",
    "di cui %(c)s di intermedi": "of which %(c)s from intermediates",
    "Dettaglio %(n)d voci": "%(n)d-line breakdown",
    "Totale reazione principale:": "Main reaction total:",
    "Totale workup/passi:": "Workup/steps total:",
    "Se procedi, il run sarà registrato come <strong>fallito</strong> "
    "(resa zero) e nessun prodotto verrà aggiunto all'inventario.":
        "If you proceed, the run will be logged as "
        "<strong>failed</strong> (zero yield) and no product will "
        "be added to inventory.",

    # ── Orders ──────────────────────────────────────────────────
    "Lista ordini": "Orders list",
    "Dettagli ordine": "Order details",
    "Modifica ordine": "Edit order",
    "Annulla ordine…": "Cancel order…",
    "Annullare definitivamente questo ordine?":
        "Definitely cancel this order?",
    "Motivo": "Reason",
    "Motivo (opzionale)": "Reason (optional)",
    "Stato corrente:": "Current status:",
    "Consegna prevista:": "Expected delivery:",
    "Consegna prevista": "Expected delivery",
    "Segna come ordinato": "Mark as ordered",
    "Numero catalogo": "Catalog number",
    "Riferimento interno": "Internal reference",
    "PO interno, numero richiesta, …":
        "Internal PO, request number, …",
    "Lista della spesa": "Shopping list",
    "Aperti": "Open",
    "Annullati": "Cancelled",
    "Totale aperti:": "Open total:",
    "Ordinato:": "Ordered:",
    "Quantità e costo effettivi": "Actual quantity and cost",
    "Spiegazione (se ricevuto parziale)":
        "Explanation (if partial)",
    "Torna agli ordini": "Back to orders",
    "Cosa includere nella lista": "What to include in the list",
    "Ultimo fornitore": "Last supplier",
    "stimato": "estimated",
    "Personalizza prima di creare": "Customize before creating",
    "Totale stimato selezionabili:":
        "Estimated total of selectable:",
    "Ordine pianificato per %(name)s.":
        "Planned order for %(name)s.",
    "Preferenze lista della spesa aggiornate.":
        "Shopping list preferences updated.",
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
    "senza codice": "without code",
    "Nessuna voce.": "No items.",

    # ── Settings ────────────────────────────────────────────────
    "Configurazione del laboratorio": "Lab configuration",
    "Valuta": "Currency",
    "Visualizzazione": "Display",
    "Esempi di formattazione": "Formatting examples",
    "Totale ordine": "Order total",
    "Codice dei Run": "Run code",
    "Codice delle preparazioni": "Preparation code",
    "Formato attuale:": "Current format:",
    "Formato del codice": "Code format",
    "Anteprima:": "Preview:",
    "anno corrente (es. 2026)": "current year (e.g. 2026)",
    "Progressività della sequenza": "Sequence progressivity",
    "codice operatore (es. RX, CG)": "operator code (e.g. RX, CG)",
    "Scegli da elenco": "Pick from list",
    "scegli…": "pick…",
    "Attuale:": "Current:",
    "Attualmente:": "Currently:",
    "Default:": "Default:",
    "Per template": "Per template",
    "Gestisci ruoli e permessi degli utenti.":
        "Manage user roles and permissions.",
    "Utente: esegue run, non modifica template. Supervisore: crea/"
    "modifica reazioni e sostanze. Amministratore: tutto.":
        "User: runs experiments, doesn't modify templates. "
        "Supervisor: creates/edits reactions and substances. "
        "Administrator: everything.",
    "Stoic non ha self-signup: gli utenti vengono creati qui da un "
    "amministratore. Comunica username e password all'utente, che "
    "potrà cambiarla dopo il primo accesso in Profilo → Cambia "
    "password.":
        "Stoic has no self-signup: users are created here by an "
        "administrator. Share the username and password with the "
        "user, who can change it after first login at Profile → "
        "Change password.",
    "può creare, modificare ed eliminare reazioni e sostanze. Non "
    "può gestire utenti, impostazioni o audit log.":
        "can create, edit and delete reactions and substances. "
        "Cannot manage users, settings or the audit log.",
    "Non puoi cambiare il tuo ruolo. Per creare un nuovo utente, "
    "usa il bottone in alto a destra.":
        "You can't change your own role. To create a new user, "
        "use the button in the top-right.",
    "Nome completo": "Full name",
    "Codice operatore": "Operator code",
    "Codice op.": "Op. code",
    "Email": "Email",
    "Gruppo predefinito": "Default group",
    "Password temporanea": "Temporary password",
    "Ultimo accesso": "Last login",
    "Aggiorna ruolo": "Update role",
    "Utente %(u)s creato. Comunica le credenziali e invitalo a "
    "cambiare la password al primo accesso.":
        "User %(u)s created. Share the credentials and ask them "
        "to change the password on first login.",
    "Impostazioni codice run aggiornate.":
        "Run code settings updated.",
    "Valuta impostata su %(c)s.": "Currency set to %(c)s.",
    "Nome completo obbligatorio.": "Full name required.",
    "Codice operatore già in uso.": "Operator code already in use.",
    "La valuta del laboratorio: usata per tutti i costi (lotti, "
    "ordini, run, statistiche).":
        "The lab currency: used for all costs (batches, orders, "
        "runs, statistics).",
    "Il codice deve essere ISO 4217 a 3 lettere (es. EUR, USD, "
    "JPY, UZS, ZMW…). Per le valute con simbolo riconosciuto verrà "
    "mostrato il simbolo (€, $, £, ¥, ₹…), altrimenti il codice "
    "stesso.":
        "The code must be ISO 4217 (3 letters: EUR, USD, JPY, "
        "UZS, ZMW…). For currencies with a recognised symbol, the "
        "symbol is shown (€, $, £, ¥, ₹…); otherwise the code "
        "itself.",
    "slug del nome miscela (es. HCl 6N → HCL6N, max 16 caratteri)":
        "slug of the mixture name (e.g. HCl 6N → HCL6N, max 16 chars)",
    "Esempio: HCL6N-2026-001, HCL1N-2026-002, ELUENTEA-2026-003.":
        "Example: HCL6N-2026-001, HCL1N-2026-002, ELUENTEA-2026-003.",
    "Esempio: HCL6N-2026-001, HCL6N-2026-002, HCL1N-2026-001.":
        "Example: HCL6N-2026-001, HCL6N-2026-002, HCL1N-2026-001.",

    # ── Encryption & backups (page renamed to "Crittografia e backup") ─
    "Crittografia e backup": "Encryption & backups",
    "Cifratura del database, backup automatici notturni, "
    "configurazione di orario e retention, ripristino.":
        "Database encryption, nightly automatic backups, "
        "schedule and retention settings, restore.",
    "Snapshot del database compressi e gestiti automaticamente.":
        "Compressed database snapshots, managed automatically.",
    "DB live cifrato (SQLCipher)": "Live DB encrypted (SQLCipher)",
    "Il file": "The file",
    "è cifrato a livello di pagina con AES-256-CBC + HMAC-SHA512. "
    "Chi accede al filesystem senza la passphrase vede dati opachi.":
        "is encrypted at the page level with AES-256-CBC + "
        "HMAC-SHA512. Anyone accessing the filesystem without the "
        "passphrase sees opaque data.",
    "(richiede Stoic fermo).": "(requires Stoic to be stopped).",
    "Per disattivare:": "To disable:",
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
    "Esegui:": "Run:",
    "Attivabile via CLI:": "Activatable via CLI:",
    "sqlcipher3 non installato.": "sqlcipher3 not installed.",
    "sul terminale di": "on the terminal of",
    "La passphrase è la stessa dei backup, quindi una sola cosa da "
    "ricordare. Il DB live cifrato è protetto contro filesystem "
    "compromessi o accessi non autorizzati al disco.":
        "The passphrase is the same as for backups, so there's "
        "only one thing to remember. The encrypted live DB is "
        "protected against compromised filesystems or unauthorised "
        "disk access.",
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
        "Anthropic, Stoic, and nobody else can help you recover them.",
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
        "I confirm: I have memorised the passphrase, the file can "
        "be deleted",
    "Elimina instance/backup.key": "Delete instance/backup.key",
    "Backup automatici attivi": "Automatic backups active",
    "Ora (UTC)": "Hour (UTC)",
    "Minuto": "Minute",
    "Conserva ultimi (giorni)": "Keep last (days)",
    "+ uno a settimana per (settimane)":
        "+ one per week for (weeks)",
    ", o assoluta.": ", or absolute.",
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
    "Backup creato: %(name)s (%(mb).2f MB).":
        "Backup created: %(name)s (%(mb).2f MB).",
    "Backup fallito: %(err)s": "Backup failed: %(err)s",
    "Conferma il ripristino spuntando la casella.":
        "Confirm the restore by ticking the checkbox.",
    "Nome file di backup non valido.": "Invalid backup filename.",
    "Ripristino effettuato da %(name)s. Riavvia l'applicazione "
    "perché le modifiche abbiano effetto.":
        "Restored from %(name)s. Restart the application for "
        "changes to take effect.",
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
        "Passphrase source set to '%(s)s'. Takes effect from "
        "Stoic's next restart.",
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
    "Eliminare definitivamente il file:":
        "Permanently delete the file:",
    "Questa operazione non è reversibile.":
        "This operation is not reversible.",
    "Elimina backup": "Delete backup",
    "Dimensione": "Size",
    "Azioni": "Actions",
    "Cifrato": "Encrypted",
    "Plain": "Plain",

    # ── Audit log page ──────────────────────────────────────────
    "Da": "From",
    "A": "To",
    "IP": "IP",
    "mostra JSON": "show JSON",
    "Errore interno": "Internal error",
    "La pagina che stai cercando non esiste.":
        "The page you are looking for does not exist.",
    "Torna alla home": "Back to home",
    "Torna alla dashboard": "Back to dashboard",

    # ── Mixture form / detail ───────────────────────────────────
    "Una miscela rappresenta una preparazione fisica (soluzione, "
    "eluente, tampone) con uno o più componenti. Per la sostanza "
    "pura usa invece il catalogo Sostanze.":
        "A mixture represents a physical preparation (solution, "
        "eluent, buffer) with one or more components. For pure "
        "substances, use the Substances catalog instead.",
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
    "Nessun componente strutturato — l'auto-suggest userà solo la "
    "quantità target.":
        "No structured components — auto-suggest will use only the "
        "target quantity.",
    "Nessun componente strutturato. Solo etichetta veloce.":
        "No structured components. Quick label only.",
    "es. 1.0 per HCl 1N": "e.g. 1.0 for HCl 1N",
    "Generato automaticamente in base alle impostazioni; modificalo "
    "se serve.":
        "Auto-generated from settings; edit it if needed.",
    "Disponibile": "Available",
    "Target": "Target",
    "Per cromatografie usa una miscela (es. EtOAc/PE 5:2) e "
    "seleziona 'quanto basta' come quantità.":
        "For chromatography use a mixture (e.g. EtOAc/PE 5:2) and "
        "select 'ad libitum' as the quantity.",
    "'quanto basta' (free): la quantità non è specificata nel "
    "template — la registri al Run. Tipico per eluenti di "
    "cromatografia.":
        "'ad libitum' (free): the quantity isn't specified in the "
        "template — you log it at Run time. Typical for "
        "chromatography eluents.",
    "es. 'HCl 1N': il sistema calcolerà le moli dalla "
    "concentrazione × volume.":
        "e.g. 'HCl 1N': the system will compute moles from "
        "concentration × volume.",
    "Tutte le miscele preparate dai precursori, ordinate dalla più "
    "recente.":
        "All mixtures prepared from precursors, newest first.",
    "Seleziona esattamente una tra Sostanza e Miscela.":
        "Select exactly one of Substance and Mixture.",
    "Non posso disattivare: ci sono lotti attivi (%(n)d)":
        "Cannot deactivate: %(n)d active batches still exist.",
    "Nessun lotto precursore selezionato. Seleziona almeno uno.":
        "No precursor batch selected. Select at least one.",
    "Errore imprevisto durante la preparazione.":
        "Unexpected error during preparation.",
    "Mostra/nascondi scheda": "Show/hide details",
    "Apri scheda completa": "Open full details",
    "es. Scaffale B-3": "e.g. Shelf B-3",

    # ── Attachments ─────────────────────────────────────────────
    "Allegati": "Attachments",
    "Allegato caricato.": "Attachment uploaded.",
    "Nessun allegato. Carica il primo qui sotto.":
        "No attachments yet. Upload the first one below.",
    "caricato da": "uploaded by",
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
    "foto, CoA, schede": "photos, CoA, datasheets",
    "(utente eliminato)": "(deleted user)",

    # ── Comments / markdown ─────────────────────────────────────
    "Aggiungi un commento… (markdown leggero: **grassetto**, "
    "*corsivo*, `codice`, [link](url), - lista)":
        "Add a comment… (light markdown: **bold**, *italic*, "
        "`code`, [link](url), - list)",
    "Il commento non può essere vuoto.": "Comment cannot be empty.",
    "Modifica del commento": "Editing comment",
    "Modificato il %(d)s": "Edited on %(d)s",
    "modificato": "edited",
    "Elimina (admin)": "Delete (admin)",
    "Le modifiche non sono visibili agli altri finché non premi "
    "'Pubblica' in fondo alla pagina.":
        "Changes are not visible to others until you press "
        "'Publish' at the bottom of the page.",
    "Modifica in corso. Premi 'Salva' per confermare o 'Annulla' per "
    "scartare le modifiche.":
        "Editing in progress. Press 'Save' to confirm or 'Cancel' "
        "to discard changes.",

    # ── File upload generic ─────────────────────────────────────
    "Nessun file selezionato.": "No file selected.",
    "File vuoto.": "Empty file.",
    "Token CSRF mancante. Riprova.": "Missing CSRF token. Retry.",
    "entity_type non valido: %(t)s": "invalid entity_type: %(t)s",
    "Errore durante il salvataggio": "Error during save",
    "Si è verificato un errore. Riprova più tardi.":
        "An error occurred. Please try again later.",

    # ── Misc / shared bits ──────────────────────────────────────
    "Si è verificato un errore. Riprova più tardi.":
        "An error occurred. Please try again later.",
    "Sigma-Aldrich, TCI, …": "Sigma-Aldrich, TCI, …",
    "Lascia vuoto per usare la quantità iniziale.":
        "Leave empty to use the initial quantity.",
    "Compila la coppia coerente con lo stato fisico (g per solidi, "
    "mL per liquidi).":
        "Fill the pair consistent with the physical state (g for "
        "solids, mL for liquids).",
    "Se non specificato, lo schema viene derivato automaticamente "
    "dai componenti.":
        "If not specified, the scheme is derived automatically "
        "from the components.",
    "Dopo aver salvato la reazione, potrai aggiungere i componenti "
    "(sostanze + ruoli + stechiometria) dalla pagina di dettaglio.":
        "After saving the reaction, you can add components "
        "(substances + roles + stoichiometry) from the detail page.",
    "Cerca per codice, titolo, sostanza, CAS, fonte…":
        "Search by code, title, substance, CAS, source…",
    "es. Spegnere con NH4Cl saturo, separare le fasi, estrarre la "
    "fase acquosa con EtOAc x 3, riunire le fasi organiche, lavare "
    "con brine, anidrificare su Na2SO4 e concentrare a secco.":
        "e.g. Quench with sat. NH4Cl, separate the phases, extract "
        "the aqueous phase with EtOAc × 3, combine the organic "
        "phases, wash with brine, dry over Na2SO4 and concentrate "
        "to dryness.",
    "es. Sciogliere il SM in DCM anidro sotto Ar, raffreddare a 0 "
    "°C, aggiungere il reagente goccia a goccia, lasciare 12 h a "
    "temperatura ambiente.":
        "e.g. Dissolve the SM in anhydrous DCM under Ar, cool to "
        "0 °C, add the reagent dropwise, leave for 12 h at room "
        "temperature.",
    "Temp. (°C)": "Temp. (°C)",
    "range:": "range:",
    "Trend": "Trend",
    "In arrivo nella Settimana 4": "Coming in Week 4",
    "Dati incompleti? Dopo l'import puoi modificare la sostanza "
    "per aggiungere campi mancanti.":
        "Incomplete data? After import you can edit the substance "
        "to add missing fields.",
    "Documento generato automaticamente. Verificare sempre la SDS "
    "ufficiale del fornitore prima dell'uso.":
        "Automatically generated document. Always check the "
        "supplier's official SDS before use.",
    "A-Z, 0-9, trattini. Max 8 caratteri. Nessun punto: la versione "
    "(.1, .2, ...) viene aggiunta automaticamente al salvataggio.":
        "A-Z, 0-9, hyphens. Max 8 characters. No dot: the version "
        "(.1, .2, ...) is appended automatically on save.",
    "Nessun dato di procedimento nel template.":
        "No procedure data in the template.",
    "Sotto questa quantità totale la sostanza apparirà negli avvisi "
    "della Dashboard.":
        "Below this total quantity the substance will appear in "
        "Dashboard alerts.",
    "Identificazione": "Identification",
    "Sintassi SMILES estesa: SM1.SM2>reagenti>prodotti oppure "
    "SM>>prodotto. Lasciare vuoto per derivazione automatica.":
        "Extended SMILES syntax: SM1.SM2>reagents>products or "
        "SM>>product. Leave empty for automatic derivation.",

    # ── Documentation pages (added in this patch) ───────────────
    "Documentazione": "Documentation",
    "Manuale utente": "User manual",
    "Manuale amministratore": "Administrator manual",
    "Manuale sviluppatore": "Developer manual",
    "Guide e manuali di Stoic.": "Stoic guides and manuals.",
    "Disponibile in italiano e inglese.":
        "Available in Italian and English.",
    "Versione italiana": "Italian version",
    "Versione inglese": "English version",
    "Manuali": "Manuals",
    "Workflow tipico in laboratorio: sostanze, reazioni, run, "
    "miscele, etichette.":
        "Typical lab workflow: substances, reactions, runs, "
        "mixtures, labels.",
    "Installazione, gestione utenti, cifratura, backup, deployment.":
        "Installation, user management, encryption, backups, "
        "deployment.",
    "Architettura, modelli, blueprint, testing, internazionalizzazione.":
        "Architecture, models, blueprints, testing, "
        "internationalisation.",
    "In questa pagina": "On this page",
    "Cambia lingua": "Switch language",

    # ── Passphrase source labels (4 modes) ──────────────────────
    # These were hardcoded as Python strings in passphrase_store.py
    # until 14.6.1; they're now lazy_gettext-wrapped so they
    # actually translate.
    "Nessuna (backup in chiaro, nessun prompt)":
        "None (plaintext backups, no prompt)",
    "Richiesta all'avvio (solo in RAM)":
        "On-boot prompt (RAM only)",
    "File instance/backup.key": "File instance/backup.key",
    "Variabile d'ambiente STOIC_BACKUP_PASSPHRASE":
        "Environment variable STOIC_BACKUP_PASSPHRASE",

    # ── Passphrase source descriptions ──────────────────────────
    "Crittografia disattivata. I backup vengono salvati in chiaro, "
    "il DB live (se cifrato) non parte. Default per chi non ha mai "
    "configurato la crittografia. Da cambiare appena attivi una "
    "delle altre modalità.":
        "Encryption disabled. Backups are saved in plaintext, the "
        "live DB (if encrypted) won't start. Default for those who "
        "have never configured encryption. Switch to another mode "
        "as soon as you enable one.",
    "Massima sicurezza contro furto del disco: la passphrase "
    "non viene mai scritta su disco. Stoic la chiede a ogni "
    "avvio e la tiene solo in RAM. Se Stoic non gira, niente "
    "decifra il DB. Implica: ogni 'make run' richiede una "
    "digitazione; i backup notturni richiedono Stoic acceso.":
        "Maximum protection against disk theft: the passphrase is "
        "never written to disk. Stoic asks for it at every start "
        "and keeps it in RAM only. If Stoic isn't running, nothing "
        "decrypts the DB. Implies: every 'make run' needs a typed "
        "passphrase; nightly backups require Stoic to be running.",
    "Comodità massima: la passphrase è in instance/backup.key "
    "(permessi 0600). Stoic la legge automaticamente al boot. "
    "Backup notturni funzionano anche se Stoic non è in uso. "
    "Vulnerabile se l'attaccante prende disco + file di chiave.":
        "Maximum convenience: the passphrase is in "
        "instance/backup.key (permissions 0600). Stoic reads it "
        "automatically at boot. Nightly backups work even if Stoic "
        "isn't in use. Vulnerable if the attacker grabs disk + "
        "keyfile.",
    "Adatta a deployment server (systemd-creds, Docker secrets, "
    "ecc): la passphrase è iniettata via env var prima del "
    "lancio. Equivalente in sicurezza al modo 'file' nella "
    "maggior parte dei casi d'uso desktop.":
        "Suited to server deployments (systemd-creds, Docker "
        "secrets, etc.): the passphrase is injected via env var "
        "before launch. Security-equivalent to 'file' mode in most "
        "desktop use cases.",

    # ── CLI hints in backup page ────────────────────────────────
    "Ferma Stoic": "Stop Stoic",
    "Riavvia": "Restart",
}


def parse_blocks(text: str) -> list[str]:
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
    new_blocks = []
    for i, block in enumerate(blocks):
        if i == 0 or block.strip().startswith("#~") or \
           "msgid " not in block or "msgstr " not in block:
            new_blocks.append(block)
            continue
        msgid = extract_msgid(block)
        if msgid is None:
            new_blocks.append(block)
            continue
        if msgid in OVERRIDES:
            block = replace_msgstr(
                block, encode_po_string(OVERRIDES[msgid])
            )
            block = drop_fuzzy(block)
            applied += 1
        new_blocks.append(block)

    out = "\n\n".join(new_blocks)
    if not out.endswith("\n"):
        out += "\n"
    po.write_text(out, encoding="utf-8")

    print(f"Applied: {applied} EN overrides "
          f"(out of {len(OVERRIDES)} total in dict).")


if __name__ == "__main__":
    main()
