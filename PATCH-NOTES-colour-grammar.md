# PATCH NOTES — colour grammar (v1.5.5)

## Why

The logo and the app did not look like the same product: four navies
and three teals coexisted, Bootstrap pink coloured every code on every
page, links and outline buttons were Bootstrap blue, badges used seven
solid colours, and nothing except the page title told the operator
which section they were in.

## The rule

- **Navy** (`--stoic-navy`, `#1f2a54`): structure and action. Header,
  page titles, links, primary and outline buttons.
- **Teal** (`--stoic-teal`, `#0a9ca7`): active right now. Current
  sidebar item (bar and icon), run in progress (badge and banner),
  focused field, checked box, page-title icon, KPI icons.
- **Grey**: data. Codes, role badges, table headers.

`--stoic-teal-text` (`#07808a`) is the same hue darkened for text:
the logo teal is 3.3:1 on white, below WCAG AA. In dark mode the
tokens are lifted (`#25b5bf`, `#45c9d2`, links `#b3c2ec`).

The navy is the one in `stoicw.pdf`. The SVG sources use `#0f1131`,
nearly black, which does not work as a header colour. The PWA PNG
icons still carry the old navy; regenerating them is left for a
separate change.

## What changed

- `static/css/app.css`: token blocks rewritten; new section
  "Colour grammar (v1.5.5)" at the end. Old tokens (`--stoic-primary`,
  `--stoic-accent`, `--stoic-logo-*`) remain as aliases so existing
  rules keep working.
- `models/run.py`: `Run.status_color` returns `"running"` for
  `in_progress` (was `"primary"`, shared with the "Reagent" role badge).
  `.badge.text-bg-running` is defined in `app.css`.
- `navigation.py` (new): `section_icon(endpoint)`, registered as a
  Jinja global. `templates/_macros/page.html` (new): `page_icon()`.
- 17 list pages use `<h1 class="page-title">{{ page_icon() }}…`;
  6 detail pages put `page_icon("crumb")` in the first breadcrumb item.
  `runs/list.html` and `settings/users.html` titles moved from `h2` to
  `h1`; the audit log title uses the sidebar icon (`shield-check`)
  instead of `file-text`.
- `base.html` `theme-color`, manifest colours, `favicon.svg`: new navy.

## Pitfall found on the way

The macro must be imported **without** `with context`. With it, Jinja
keeps the render context alive after the request, and with it every
ORM object on the page. In the test suite the outer app context is
shared between requests, so SQLAlchemy's weak identity map held on to
a stale `Run`, and `test_recovery_form_appears_only_in_progress` saw
the old status. `section_icon` is therefore a Jinja global, callable
from a macro imported without context.

## Not in this patch

- Forms, onboarding, reports and settings sub-pages keep their own
  headings; they pick up the colours but not the icon.
- `Esegui run` stays `btn-success`: it is the one "go" on the page.
- The inventory table overflows the page on phones. Layout issue, to
  be handled separately.
- Bootstrap, HTMX and Lucide still load from CDN (Lucide `@latest`).

## Verify

- Sidebar footer shows `v1.5.5`.
- Storico run: the running run is the only teal badge, with a dot.
- Run page in progress: teal banner, `in esecuzione` badge in the
  breadcrumb with the history icon.
- Codes (lot, CAS) are grey monospace, not pink.
- Dark mode: sidebar text readable, titles light, links periwinkle.
