# Stoic — patch 15.4 (CHANGELOG aggiornato + tag v0.9.0)

Ultima patch della Settimana 7 prima del release pubblico.
Aggiorna il CHANGELOG.md con la documentazione completa di
v0.9.0 e include le istruzioni per creare il tag annotato
`v0.9.0` da pushare su GitHub.

## File modificati

- `CHANGELOG.md` — riscritto. Adesso documenta:
  - Feature surface completa di v0.9.0 (catalogo, inventario,
    miscele, reazioni, run, preparazioni, ordini, report, backup,
    audit, PDF, CLI, installer, docs, i18n, suite test)
  - Cambiamenti dalla pre-release (file aggiunti, fix bug)
  - Roll-up degli internal milestone (Settimane 1-7)
  - Sezione [Unreleased] aggiornata col path verso v1.0.0

Nessun codice modificato, nessun test cambiato.

## Applicazione

```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-eln-patch15.4.tar.gz -C ~/Projects/
git add CHANGELOG.md
git commit -m "patch 15.4: CHANGELOG completo per v0.9.0"
git push
```

## Creazione tag v0.9.0

Dopo aver committato il CHANGELOG, crea il tag annotato sul
commit HEAD. Tag annotati (vs lightweight) sono raccomandati
per release: contengono messaggio, autore, data — diventano
oggetti git interrogabili.

```bash
cd ~/Projects/stoic-eln

# Crea il tag annotato
git tag -a v0.9.0 -m "Stoic v0.9.0 — first public release

Open-source ELN/LIMS for small chemistry labs.
Licensed under AGPLv3 with CLA.

See CHANGELOG.md for complete feature surface and history."

# Verifica
git tag -l -n5

# Pusha il tag su GitHub
git push origin v0.9.0
```

Dopo il `git push origin v0.9.0`, su GitHub vedrai il tag in
**Tags** (https://github.com/the-stoic-authors/stoic/tags).

## Creazione Release su GitHub

GitHub distingue **tag** (oggetto git) da **release** (entity
con titolo, body, assets opzionali).

1. Vai su https://github.com/the-stoic-authors/stoic/releases/new
2. **Choose a tag**: seleziona `v0.9.0` dalla dropdown
3. **Release title**: `Stoic v0.9.0 — first public release`
4. **Release notes body**: incolla il blocco qui sotto

### Body della Release (copia-incolla)

```markdown
# Stoic v0.9.0 — first public release

Stoic is an open-source Electronic Lab Notebook (ELN) and
Laboratory Information Management System (LIMS) for small
chemistry labs.

This is the first public release: feature-complete, tested
(480 tests, 100% passing), AGPLv3 licensed, ready for adoption
by labs that want full control over their data.

## What's in v0.9.0

- **Substances catalogue** with GHS hazards, PubChem import,
  CAS/SMILES/InChI/IUPAC, density, melting/boiling points
- **Inventory lots** with expiry tracking, cost, supplier,
  batch code, location, low-stock alerts
- **Mixtures** as first-class entities including
  mixture-as-component support (HCl 6N from HCl 12N stock)
- **Reactions** as versioned templates with components,
  step components (workup additions), and SVG schemes
- **Runs** at user-chosen scale with derived hazards and
  per-component lot picking
- **Mixture preparations** with imputed cost and derived expiry
- **Orders** plan/order/receive workflow
- **Spending reports** (week/month/quarter/year)
- **Encrypted backups** (AES-256-GCM + Argon2id) and optional
  live database encryption (SQLCipher)
- **PDF artifacts**: labels (Avery/Brother), SDS, run reports,
  audit log
- **Cross-platform CLI** with macOS launchd and Linux systemd-user
  daemon installation
- **One-shot installers** for macOS, Debian/Ubuntu, Raspberry Pi

## Quick install

**macOS**:
```bash
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-macos.sh | bash
```

**Debian/Ubuntu/Pi**:
```bash
curl -fsSL https://raw.githubusercontent.com/the-stoic-authors/stoic/main/scripts/installers/install-linux.sh | bash
```

Both installers take a fresh machine to a running Stoic in
3-10 minutes. See [scripts/installers/README.md](scripts/installers/README.md)
for details, including Raspberry Pi headless deployment.

After install, open http://127.0.0.1:5001 and log in with
`admin` / `admin123` (change the password on first login).

## Status

v0.9.0 is the first public release. The `.9` suffix is honest:
the software is complete and runs, but I want a few weeks of
real-world feedback before committing to v1.0 API stability.

Bug reports, feature requests, and contributions welcome via
the [issues page](https://github.com/the-stoic-authors/stoic/issues).
For security disclosures, please email
[the-stoic-authors@proton.me](mailto:the-stoic-authors@proton.me)
privately.

## License

AGPLv3 — see [LICENSE](LICENSE). Contributors retain copyright
under a CLA that preserves dual-licensing options for the
future ([CLA.md](CLA.md)).

---

Full changelog: [CHANGELOG.md](CHANGELOG.md)
```

5. **Set as the latest release**: già spuntato di default
6. **Pre-release**: lascia non spuntato (v0.9.0 è un release
   pubblico stabile a livello di funzionalità, non un'alpha)
7. Click **Publish release**

A questo punto Stoic v0.9.0 è ufficialmente rilasciato. Sulla
homepage del repo apparirà la sezione "Latest release: v0.9.0"
nella sidebar destra.

## Backlog post-release

Niente più Settimana 7 da fare. Da qui in avanti il lavoro è
standard "open source maintenance":

- Rispondere a issue che arrivano
- Patch incrementali (15.5, 15.6, ...) come commit normali
- Tag intermedi `v0.9.x` per bugfix release minori
- Quando l'API si sente stabile e nessun breaking change è
  imminente: bump a `v1.0.0` con release note dedicata
- Backlog feature documentato in `[Unreleased]` del CHANGELOG:
  "Plan order" per miscele commerciali, `prep_service` con
  cascade scarico inventario per mixture-as-component

## Verifica finale

Dopo aver pushato tag + release, controlla che tutto sia
visibile pubblicamente:

```bash
# Apri la release page
open https://github.com/the-stoic-authors/stoic/releases/tag/v0.9.0
```

Sulla homepage del repo (`https://github.com/the-stoic-authors/stoic`)
dovresti vedere sulla sidebar destra:

- **About** (description + topics)
- **Latest release** v0.9.0
- **Languages**: Python (~85%), HTML, CSS, JavaScript
- **License**: AGPL-3.0

Se tutto è coerente, Stoic v0.9.0 è ufficialmente nel mondo.
