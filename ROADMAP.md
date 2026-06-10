# Stoic — Roadmap to v1.0

v1.0 means: **a motivated stranger with a spare machine can install
Stoic, trust it with lab data, and succeed without talking to us.**
("Level 2" self-hosted open source: installable, documented,
maintained.)

When every box below is checked, we tag `v1.0.0` and publish the
first official Docker image to `ghcr.io/the-stoic-authors/stoic`.

## Release checklist

### Deployment

- [x] Production WSGI entrypoint (gunicorn, master-only scheduler)
- [x] Docker + Caddy stack with automatic HTTPS (`docker compose up -d`)
- [x] CI builds and smoke-tests the image on every push
- [x] One-command Linux installer (`install-linux.sh`)
- [ ] Live validation on a real lab server (clean Ubuntu install,
      LAN clients, iPad PWA with trusted CA)
- [ ] Docker image published to ghcr.io on release tags
- [ ] Multi-arch image (amd64 + arm64) so Raspberry Pi is the same
      one-command experience

### Data safety

- [x] Nightly automatic backups (AES-256-GCM encryption optional)
- [x] Live-DB encryption via SQLCipher (native installs)
- [ ] Backup restore verified end-to-end as a routine check, with a
      visible "last verified" indicator in the UI
- [ ] Off-site backup story documented (rsync/rclone from the
      backup volume to NAS or cloud)

### Product

- [x] Onboarding wizard (lab name, currency, run-code format)
- [x] PWA install support (manifest, icons, iOS meta)
- [x] Bench mode (tablet kiosk UX for run execution)
- [ ] Global search (Cmd+K) across substances, lots, reactions,
      runs, mixtures
- [ ] "Come si fa" tutorial library (written last, against the
      stable v1.0 UI, so screenshots don't rot)

### Project hygiene

- [x] Full IT + EN UI and manuals
- [x] CI green on Linux + macOS, Python 3.11 + 3.12
- [ ] CHANGELOG.md updated for v1.0.0
- [ ] README install paths verified against a clean machine

## Post-v1.0 candidates (unordered)

- Raspberry Pi performance audit on real hardware
- Service worker / offline support for the PWA
- Tailscale deployment recipe (zero-config HTTPS + remote access)
- ARM-compatible SQLCipher build inside the Docker image
- Read-only API tokens for instrument integrations

## How this file is maintained

Edited in the same commit as the work it describes. If a box is
checked but the feature doesn't work on a clean install, the box
was checked too early — reopen it.
