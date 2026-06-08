"""Stoic ELN — Onboarding wizard routes.

Five views in a linear flow:

    /onboarding              → welcome page (intro + start button)
    /onboarding/lab          → step 1: lab name
    /onboarding/currency     → step 2: currency
    /onboarding/run-code     → step 3: run/prep code format
    /onboarding/done         → step 4: confirmation + mark complete

The user can skip the wizard at any step (the AppSetting flag is
not marked completed; the wizard reappears at the next admin login).
Confirming the last step writes ``onboarding_completed_at`` and
exempts subsequent admin logins.

The wizard is admin-only. The redirect-on-login behaviour is wired
in ``stoic_eln.__init__`` via a before_request hook.
"""

from __future__ import annotations

from datetime import datetime, UTC

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from stoic_eln.blueprints._decorators import admin_required
from stoic_eln.blueprints.onboarding import bp
from stoic_eln.models.settings import AppSetting
from stoic_eln.services import currency as currency_service
from stoic_eln.services import run_code as run_code_service


# AppSetting keys used by the wizard
KEY_COMPLETED_AT = "onboarding.completed_at"
KEY_LAB_NAME = "lab.name"


def is_completed() -> bool:
    """Whether the onboarding wizard has been completed at least once.

    Used by the global before_request hook in ``stoic_eln.__init__``
    to decide whether to redirect admins to the wizard.
    """
    return AppSetting.get(KEY_COMPLETED_AT) is not None


def get_lab_name(default: str = "Stoic") -> str:
    """Return the lab name from AppSetting (wizard or settings page),
    falling back to ``default`` if not set. Used by the template
    context processor; previously this read from ``app.config``."""
    return AppSetting.get(KEY_LAB_NAME) or default


@bp.route("/")
@login_required
@admin_required
def index():
    """Welcome page. Shows what the wizard will do and a 'Start' button."""
    return render_template(
        "onboarding/welcome.html",
        already_completed=is_completed(),
    )


@bp.route("/lab", methods=["GET", "POST"])
@login_required
@admin_required
def step_lab():
    """Step 1: lab name."""
    current = AppSetting.get(KEY_LAB_NAME) or ""
    if request.method == "POST":
        name = (request.form.get("lab_name") or "").strip()
        if not name:
            flash("Inserisci il nome del laboratorio.", "warning")
            return render_template("onboarding/step_lab.html", current=current)
        AppSetting.set(KEY_LAB_NAME, name)
        return redirect(url_for("onboarding.step_currency"))
    return render_template("onboarding/step_lab.html", current=current)


@bp.route("/currency", methods=["GET", "POST"])
@login_required
@admin_required
def step_currency():
    """Step 2: currency.

    The wizard offers a short dropdown of common codes; the full
    /settings/currency page remains available later for less
    common cases.
    """
    current = currency_service.get_currency_code()
    if request.method == "POST":
        code = (request.form.get("currency") or "").strip().upper()
        if not code or len(code) != 3 or not code.isalpha():
            flash("Codice valuta non valido (devono essere 3 lettere ISO).", "warning")
            return render_template(
                "onboarding/step_currency.html",
                current=current,
                common_codes=currency_service.COMMON_CODES,
            )
        currency_service.set_currency_code(code)
        return redirect(url_for("onboarding.step_run_code"))
    return render_template(
        "onboarding/step_currency.html",
        current=current,
        common_codes=currency_service.COMMON_CODES,
    )


# Predefined run-code presets shown in the wizard. The user can
# always pick a fully custom format on the Settings → Codifica run
# page after the wizard.
RUN_CODE_PRESETS = [
    {
        "label": "Stoic standard",
        "format": "{op}-{tem}-{year}-{seq:03d}",
        "scope": "lab",
        "preview": "RR-SUZ-2026-001",
    },
    {
        "label": "Solo anno e sequenza",
        "format": "{year}-{seq:04d}",
        "scope": "lab",
        "preview": "2026-0001",
    },
    {
        "label": "Anno corto + sequenza",
        "format": "{yy}{seq:04d}",
        "scope": "lab",
        "preview": "260001",
    },
    {
        "label": "Operatore + sequenza",
        "format": "{op}-{seq:04d}",
        "scope": "operator",
        "preview": "RR-0001",
    },
]


@bp.route("/run-code", methods=["GET", "POST"])
@login_required
@admin_required
def step_run_code():
    """Step 3: run/prep code format.

    Offers a short list of presets. For custom formats, the user can
    visit /settings/run-code after the wizard.
    """
    if request.method == "POST":
        preset_idx = request.form.get("preset", "")
        try:
            idx = int(preset_idx)
            preset = RUN_CODE_PRESETS[idx]
        except (ValueError, IndexError):
            flash("Seleziona un formato.", "warning")
            return render_template(
                "onboarding/step_run_code.html",
                presets=RUN_CODE_PRESETS,
                current_format=run_code_service.get_format(),
            )
        run_code_service.set_format(preset["format"])
        run_code_service.set_scope(preset["scope"])
        return redirect(url_for("onboarding.step_done"))
    return render_template(
        "onboarding/step_run_code.html",
        presets=RUN_CODE_PRESETS,
        current_format=run_code_service.get_format(),
    )


@bp.route("/done", methods=["GET", "POST"])
@login_required
@admin_required
def step_done():
    """Step 4: review + confirmation. Marks onboarding as completed."""
    summary = {
        "lab_name": AppSetting.get(KEY_LAB_NAME) or "—",
        "currency": currency_service.get_currency_code(),
        "run_format": run_code_service.get_format(),
        "run_scope": run_code_service.get_scope(),
    }
    if request.method == "POST":
        AppSetting.set(KEY_COMPLETED_AT, datetime.now(UTC).isoformat())
        flash("Configurazione iniziale completata.", "success")
        return redirect(url_for("main.dashboard"))
    return render_template("onboarding/step_done.html", summary=summary)


@bp.route("/skip")
@login_required
@admin_required
def skip():
    """Bail out of the wizard without marking it complete.

    The wizard will reappear at the next admin login (unless the
    admin explicitly completes it later). Settings already saved
    during the wizard are kept.
    """
    flash(
        "Procedura saltata. Puoi rieseguirla in qualsiasi momento da /onboarding.",
        "info",
    )
    return redirect(url_for("main.dashboard"))
