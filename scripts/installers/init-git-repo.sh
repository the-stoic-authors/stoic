#!/usr/bin/env bash
#
# init-git-repo.sh — one-shot git initialisation for Stoic.
#
# Run from the Stoic repo root (~/Projects/stoic-eln). Sets up
# the local git repository with sensible config and a clean
# initial commit. No push to a remote — that's a separate
# decision.
#
# What it does:
#   1. Verifies we're in the Stoic project root.
#   2. Runs `git init` (idempotent — won't reset existing history).
#   3. Configures author identity (name + email).
#   4. Adds a .gitattributes for line-ending consistency.
#   5. Stages everything (respecting .gitignore — instance/ stays
#      private).
#   6. Creates the initial commit with a meaningful message.
#   7. Shows the result.
#
# Idempotent: re-running after the initial commit is a no-op
# (script detects the existing commit and exits).
#
# Run with:
#   cd ~/Projects/stoic-eln
#   bash init-git-repo.sh

set -euo pipefail

# ─── Output helpers ──────────────────────────────────────────────

if [ -t 1 ]; then
    GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'
    RED='\033[0;31m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'
else
    GREEN=''; BLUE=''; YELLOW=''; RED=''; BOLD=''; DIM=''; RESET=''
fi

ok()      { printf "${GREEN}✓${RESET} %s\n" "$*"; }
info()    { printf "${BLUE}→${RESET} %s\n" "$*"; }
warn()    { printf "${YELLOW}⚠${RESET} %s\n" "$*"; }
die()     { printf "${RED}✗${RESET} %s\n" "$*" >&2; exit 1; }
header()  { printf "\n${BOLD}━━ %s ━━${RESET}\n" "$*"; }

# ─── Step 1: verify location ─────────────────────────────────────

header "Stoic — local git initialisation"

# We expect to be in the project root, identified by the
# combination of pyproject.toml + stoic_eln/ directory.
[ -f "pyproject.toml" ] || die "No pyproject.toml here. Run from the Stoic project root (cd ~/Projects/stoic-eln)."
[ -d "stoic_eln" ]      || die "No stoic_eln/ directory here. Wrong location."
grep -q "^name = \"stoic-eln\"" pyproject.toml || \
    die "pyproject.toml doesn't look like Stoic's. Wrong project?"

ok "In Stoic project root: $(pwd)"

# ─── Step 2: git init (idempotent) ───────────────────────────────

if [ -d .git ]; then
    info ".git directory already exists"
    if git rev-parse HEAD >/dev/null 2>&1; then
        warn "An initial commit already exists:"
        git log --oneline -1
        echo
        warn "Nothing to do. If you want to redo this, delete .git first:"
        warn "  rm -rf .git    (DESTRUCTIVE — only if you know what you're doing)"
        exit 0
    fi
    info "...but with no commits yet. Continuing."
else
    info "Running 'git init'"
    git init -q -b main
    ok "Initialised empty Git repository on branch 'main'"
fi

# ─── Step 3: configure author identity ───────────────────────────

header "Configuring author identity"

# Prefer the global identity if already set sensibly. Otherwise
# set the project-local one to the canonical Stoic authors line.
GLOBAL_NAME=$(git config --global user.name 2>/dev/null || echo "")
GLOBAL_EMAIL=$(git config --global user.email 2>/dev/null || echo "")

if [ -n "$GLOBAL_NAME" ] && [ -n "$GLOBAL_EMAIL" ]; then
    ok "Using global git identity: $GLOBAL_NAME <$GLOBAL_EMAIL>"
    info "Override locally with: git config user.name '...' && git config user.email '...'"
else
    info "No global git identity — setting one for this repo only"
    git config user.name "The Stoic Authors"
    git config user.email "the-stoic-authors@proton.me"
    ok "Set local identity: The Stoic Authors <the-stoic-authors@proton.me>"
fi

# ─── Step 4: .gitattributes ──────────────────────────────────────

header "Configuring line endings"

if [ -f .gitattributes ]; then
    ok ".gitattributes already exists, leaving as-is"
else
    info "Writing .gitattributes for cross-platform line endings"
    cat > .gitattributes <<'EOF'
# Stoic — git attributes for cross-platform consistency.
#
# Force LF line endings on all text files. Without this, contributors
# on Windows (via WSL or VS Code) could commit CRLF, breaking shell
# scripts and confusing diffs.

* text=auto eol=lf

# Shell scripts must be LF — execution depends on it.
*.sh text eol=lf

# Python / templates / config — always LF.
*.py     text eol=lf
*.toml   text eol=lf
*.html   text eol=lf
*.css    text eol=lf
*.js     text eol=lf
*.md     text eol=lf
*.yml    text eol=lf
*.yaml   text eol=lf

# Binary files — declare explicitly so git doesn't try to diff them.
*.png    binary
*.jpg    binary
*.jpeg   binary
*.gif    binary
*.pdf    binary
*.db     binary
*.sqlite binary
*.svg    text eol=lf
*.mo     binary
EOF
    ok ".gitattributes created"
fi

# ─── Step 5: stage everything (respecting .gitignore) ────────────

header "Staging files"

git add .

# Show a brief summary of what's being committed (number of files,
# total lines). Helpful sanity check before the commit.
NUM_FILES=$(git diff --cached --name-only | wc -l | tr -d ' ')
info "Staged: $NUM_FILES files"

# Sanity-check that .gitignore is doing its job — instance/ must
# NOT be staged. If it is, abort: committing instance/ would
# publish the live DB and any encryption keys.
if git diff --cached --name-only | grep -q "^instance/"; then
    die "instance/ is staged — .gitignore is not working. Refusing to continue."
fi
ok "instance/ correctly excluded from commit"

# Same for .venv (would be huge and platform-specific).
if git diff --cached --name-only | grep -q "^\.venv/"; then
    die ".venv/ is staged — .gitignore is broken. Refusing to continue."
fi
ok ".venv/ correctly excluded from commit"

# ─── Step 6: initial commit ──────────────────────────────────────

header "Creating initial commit"

git commit -q -m "Initial public state — Stoic ELN v0.9.0

Pre-release snapshot of Stoic ELN, an open-source electronic
lab notebook and LIMS for small chemistry labs.

Includes:
- Substances + GHS hazards + lots inventory
- Mixtures (with mixtures-as-components support, patch 14.6.7)
- Reactions with steps, components, and PNG scheme rendering
- Run setup workflow with derived hazard pictograms
- Preparation flow with cost imputation and derived expiry
- Order workflow (planning, receiving, lot creation)
- Encrypted backups (SQLCipher + age-style passphrase)
- Spending report with weekly/monthly/quarterly/yearly buckets
- Cross-platform 'stoic' CLI (macOS launchd, Linux systemd)
- macOS one-shot installer script

Licensed under AGPLv3 with CLA preserving relicensing options.
History before this point is preserved in PATCH-NOTES.md files
distributed with each tarball-based patch from the development
phase."

ok "Initial commit created"
git log --oneline -1

# ─── Done ────────────────────────────────────────────────────────

header "Done"

cat <<EOF

${BOLD}Git is set up.${RESET} From here on, every change you make should
be committed:

    ${DIM}# After applying a new patch from Claude:${RESET}
    git add .
    git commit -m "patch X.Y.Z: short summary"

    ${DIM}# Inspect history:${RESET}
    git log --oneline
    git log --stat -1   # detailed view of last commit

    ${DIM}# Undo last commit (keep changes staged):${RESET}
    git reset --soft HEAD~1

    ${DIM}# See uncommitted changes:${RESET}
    git status
    git diff

${BOLD}Next steps when you're ready to go public:${RESET}

1. Create the GitHub organisation:
     https://github.com/account/organizations/new
     → name: 'the-stoic-authors'
2. Create the repository inside it:
     https://github.com/organizations/the-stoic-authors/repositories/new
     → name: 'stoic', visibility: public, no README/LICENSE
     (we already have them)
3. Add the remote and push:
     git remote add origin git@github.com:the-stoic-authors/stoic.git
     git push -u origin main

Until you push, this repo lives only on your Mac. That's fine —
you can iterate locally as long as you want.

EOF
