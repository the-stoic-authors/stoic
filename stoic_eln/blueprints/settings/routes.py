"""Stoic ELN — Settings routes (admin only)."""

from __future__ import annotations

from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from stoic_eln.blueprints.settings import bp
from stoic_eln.extensions import db
from stoic_eln.services import run_code as run_code_service
from stoic_eln.services.audit import log_event


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


@bp.route("/")
@login_required
@admin_required
def index():
    """Landing page — shows the available settings groups."""
    from stoic_eln.services import prep_code as prep_code_service
    from stoic_eln.services.currency import get_currency_code

    return render_template(
        "settings/index.html",
        run_code_format=run_code_service.get_format(),
        run_code_scope=run_code_service.get_scope(),
        run_code_preview=run_code_service.preview_run_code(),
        prep_code_format=prep_code_service.get_format(),
        prep_code_scope=prep_code_service.get_scope(),
        prep_code_preview=prep_code_service.preview_prep_code(),
        currency_code=get_currency_code(),
    )


@bp.route("/run-code", methods=["GET", "POST"])
@login_required
@admin_required
def run_code():
    """Edit the run-code format and sequence scope."""
    if request.method == "POST":
        new_format = (request.form.get("format") or "").strip()
        new_scope = (request.form.get("scope") or "").strip()

        try:
            run_code_service.set_format(new_format)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("settings.run_code"))

        try:
            run_code_service.set_scope(new_scope)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("settings.run_code"))

        flash(_("Impostazioni codice run aggiornate."), "success")
        return redirect(url_for("settings.run_code"))

    return render_template(
        "settings/run_code.html",
        current_format=run_code_service.get_format(),
        current_scope=run_code_service.get_scope(),
        default_format=run_code_service.DEFAULT_FORMAT,
        default_scope=run_code_service.DEFAULT_SCOPE,
        scopes=run_code_service.SCOPES,
        placeholders=run_code_service.PLACEHOLDERS,
        preview=run_code_service.preview_run_code(),
    )


@bp.route("/run-code/preview", methods=["POST"])
@login_required
@admin_required
def run_code_preview():
    """HTMX endpoint: re-render the preview when the user types a new format."""
    fmt = (request.form.get("format") or "").strip()
    try:
        run_code_service.validate_format(fmt)
        sample = run_code_service.preview_run_code(fmt=fmt)
        return f'<code class="text-success">{sample}</code>'
    except ValueError as e:
        return f'<code class="text-danger">⚠ {e}</code>'


# ─── Prep code (Settimana 6 patch 13.3) ──────────────────────────


@bp.route("/prep-code", methods=["GET", "POST"])
@login_required
@admin_required
def prep_code():
    """Edit the mixture-preparation code format and sequence scope.

    Parallel to ``run_code`` but for ``MixturePrep`` codes. Placeholders
    are different (no operator/template — just mixture name + year +
    sequence) and scopes are simpler (``lab`` or ``mix``).
    """
    from stoic_eln.services import prep_code as prep_code_service

    if request.method == "POST":
        new_format = (request.form.get("format") or "").strip()
        new_scope = (request.form.get("scope") or "").strip()

        try:
            prep_code_service.set_format(new_format)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("settings.prep_code"))

        try:
            prep_code_service.set_scope(new_scope)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("settings.prep_code"))

        log_event(
            action="update",
            entity_type="settings",
            details={"setting": "prep_code", "format": new_format, "scope": new_scope},
        )
        flash(_("Impostazioni codice preparazione aggiornate."), "success")
        return redirect(url_for("settings.prep_code"))

    return render_template(
        "settings/prep_code.html",
        current_format=prep_code_service.get_format(),
        current_scope=prep_code_service.get_scope(),
        default_format=prep_code_service.DEFAULT_FORMAT,
        default_scope=prep_code_service.DEFAULT_SCOPE,
        scopes=prep_code_service.SCOPES,
        placeholders=prep_code_service.PLACEHOLDERS,
        preview=prep_code_service.preview_prep_code(),
    )


@bp.route("/prep-code/preview", methods=["POST"])
@login_required
@admin_required
def prep_code_preview():
    """HTMX endpoint: re-render the preview when the user types a new format."""
    from stoic_eln.services import prep_code as prep_code_service

    fmt = (request.form.get("format") or "").strip()
    try:
        prep_code_service.validate_format(fmt)
        sample = prep_code_service.preview_prep_code(fmt=fmt)
        return f'<code class="text-success">{sample}</code>'
    except ValueError as e:
        return f'<code class="text-danger">⚠ {e}</code>'


# ─── Users management ───────────────────────────────────────────────────────


@bp.route("/users", methods=["GET"])
@login_required
@admin_required
def users():
    """List all users with their role and active status."""
    from stoic_eln.extensions import db
    from stoic_eln.models.user import User

    users_list = db.session.query(User).order_by(User.username).all()
    return render_template("settings/users.html", users=users_list)


@bp.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@admin_required
def update_user_role(user_id: int):
    """Change a user's role between user / supervisor / admin."""
    from stoic_eln.extensions import db
    from stoic_eln.models.user import User

    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    new_role = (request.form.get("role") or "").strip()
    if new_role not in ("user", "supervisor", "admin"):
        flash(_("Ruolo non valido."), "danger")
        return redirect(url_for("settings.users"))
    # Don't allow demoting the last admin (lockout protection)
    if user.role == "admin" and new_role != "admin":
        n_admins = db.session.query(User).filter(User.role == "admin").count()
        if n_admins <= 1:
            flash(_("Non puoi rimuovere l'ultimo amministratore."), "danger")
            return redirect(url_for("settings.users"))
    user.role = new_role
    user.sync_role_flags()
    db.session.commit()
    flash(_("Ruolo aggiornato per %(name)s.", name=user.username), "success")
    return redirect(url_for("settings.users"))


# ─── Currency (Settimana 6 patch 6.1) ────────────────────────────


@bp.route("/currency", methods=["GET"])
@login_required
@admin_required
def currency():
    from stoic_eln.services.currency import (
        COMMON_CODES,
        get_currency_code,
        _SYMBOLS,
    )

    return render_template(
        "settings/currency.html",
        current_code=get_currency_code(),
        common_codes=COMMON_CODES,
        symbols=_SYMBOLS,
    )


@bp.route("/currency/update", methods=["POST"])
@login_required
@admin_required
def update_currency():
    from stoic_eln.services.currency import set_currency_code

    # Free-text field wins over the dropdown if both are set
    code = (request.form.get("code") or "").strip()
    if not code:
        code = (request.form.get("code_select") or "").strip()
    try:
        cleaned = set_currency_code(code)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("settings.currency"))
    flash(_("Valuta impostata su %(c)s.", c=cleaned), "success")
    return redirect(url_for("settings.currency"))


# ─── Audit log (Settimana 6 patch 8) ───────────────────────────────


def _parse_audit_filters():
    """Extract AuditFilters from request.args (or POST data)."""
    from datetime import datetime as _dt
    from stoic_eln.services.audit_query import AuditFilters

    def _int(name):
        raw = (request.args.get(name) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _date(name):
        raw = (request.args.get(name) or "").strip()
        if not raw:
            return None
        try:
            return _dt.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _str(name):
        raw = (request.args.get(name) or "").strip()
        return raw or None

    return AuditFilters(
        user_id=_int("user_id"),
        action=_str("action"),
        entity_type=_str("entity_type"),
        date_from=_date("date_from"),
        date_to=_date("date_to"),
        q=_str("q"),
    )


@bp.route("/audit-log", methods=["GET"])
@login_required
@admin_required
def audit_log():
    """Paginated, filtered audit log for admins."""
    from stoic_eln.services.audit_query import (
        query_events,
        distinct_actions,
        distinct_entity_types,
        distinct_users,
        label_for_action,
    )

    filters = _parse_audit_filters()
    page = request.args.get("page", default=1, type=int) or 1
    page_size = min(max(request.args.get("page_size", default=50, type=int) or 50, 10), 500)

    page_data = query_events(filters, page=page, page_size=page_size)

    return render_template(
        "settings/audit_log.html",
        page_data=page_data,
        filters=filters,
        actions=distinct_actions(),
        entity_types=distinct_entity_types(),
        users=distinct_users(),
        label_for_action=label_for_action,
    )


@bp.route("/audit-log/export.csv", methods=["GET"])
@login_required
@admin_required
def audit_log_export_csv():
    """Download all matching events as CSV."""
    from stoic_eln.services.audit_query import export_csv

    filters = _parse_audit_filters()
    csv_text = export_csv(filters)
    from flask import Response
    from datetime import datetime as _dt

    fname = f"audit_log_{_dt.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@bp.route("/audit-log/export.pdf", methods=["GET"])
@login_required
@admin_required
def audit_log_export_pdf():
    """Download all matching events as a PDF report."""
    from stoic_eln.services.audit_query import (
        query_events,
        label_for_action,
    )
    from stoic_eln.services.pdf_audit import render_audit_log_pdf

    filters = _parse_audit_filters()
    # All events (no paging) but capped to avoid runaway PDFs
    page = query_events(filters, page=1, page_size=5000)
    pdf_bytes = render_audit_log_pdf(
        events=page.events,
        filters=filters,
        label_for_action=label_for_action,
        truncated=(page.total > len(page.events)),
        total_count=page.total,
    )
    from flask import Response
    from datetime import datetime as _dt

    fname = f"audit_log_{_dt.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ─── User creation (Settimana 6 patch 8.5) ────────────────────────


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_user():
    """Admin-only form to create a new user with a temporary password.

    No self-signup: this is a lab tool and users are authorised
    explicitly. Admin gives the credentials to the new user, who
    can change their password from /auth/password.
    """
    from stoic_eln.models import Group
    from stoic_eln.models.user import User

    groups = (
        db.session.query(Group).filter(Group.is_active.is_(True)).order_by(Group.name.asc()).all()
    )

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        full_name = (request.form.get("full_name") or "").strip()
        operator_code = (request.form.get("operator_code") or "").strip() or None
        password = (request.form.get("password") or "").strip()
        password_confirm = (request.form.get("password_confirm") or "").strip()
        role = (request.form.get("role") or "user").strip()
        locale = (request.form.get("locale") or "it").strip()
        email = (request.form.get("email") or "").strip() or None
        default_group_id_raw = (request.form.get("default_group_id") or "").strip()

        # Validate
        errors = []
        if not username:
            errors.append(_("Username obbligatorio."))
        elif db.session.query(User).filter_by(username=username).first():
            errors.append(_("Username già in uso."))
        if not full_name:
            errors.append(_("Nome completo obbligatorio."))
        if not password or len(password) < 6:
            errors.append(_("Password obbligatoria (almeno 6 caratteri)."))
        if password != password_confirm:
            errors.append(_("Le password non coincidono."))
        if role not in ("user", "supervisor", "admin"):
            errors.append(_("Ruolo non valido."))
        if operator_code and (
            db.session.query(User).filter_by(operator_code=operator_code).first()
        ):
            errors.append(_("Codice operatore già in uso."))

        try:
            default_group_id = int(default_group_id_raw) if default_group_id_raw else None
        except ValueError:
            default_group_id = None

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "settings/new_user.html",
                form_data={
                    "username": username,
                    "full_name": full_name,
                    "operator_code": operator_code or "",
                    "role": role,
                    "locale": locale,
                    "email": email or "",
                    "default_group_id": default_group_id_raw,
                },
                groups=groups,
            )

        u = User(
            username=username,
            full_name=full_name,
            email=email,
            operator_code=operator_code,
            role=role,
            is_admin=(role == "admin"),
            is_active=True,
            locale=locale,
            default_group_id=default_group_id,
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        log_event(
            action="create",
            entity_type="user",
            entity_id=u.id,
            details={"username": username, "role": role},
        )
        flash(
            _(
                "Utente %(u)s creato. Comunica le credenziali e invitalo a "
                "cambiare la password al primo accesso.",
                u=username,
            ),
            "success",
        )
        return redirect(url_for("settings.users"))

    return render_template(
        "settings/new_user.html",
        form_data={},
        groups=groups,
    )


# ── Backups ──────────────────────────────────────────────────────


@bp.route("/backups")
@login_required
@admin_required
def backups():
    """List backup files with sizes, dates, and action buttons.

    Shows configured schedule and retention so the admin sees at a
    glance what's about to happen.
    """
    from pathlib import Path
    from flask import current_app
    from stoic_eln.services import backup as backup_service
    from stoic_eln.services import db_crypto

    settings = backup_service.get_settings()
    items = backup_service.list_backups()

    # Live DB encryption status (patch 14.2)
    db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    live_db_encrypted = False
    if db_uri.startswith("sqlite:///"):
        live_db_path = Path(db_uri[len("sqlite:///") :])
        if live_db_path.exists() and not str(live_db_path).startswith(":memory"):
            live_db_encrypted = db_crypto.is_encrypted_db(live_db_path)

    # Passphrase source info (patch 14.3)
    from stoic_eln.services import passphrase_store

    pp_source = passphrase_store.current_source()
    pp_sources = [
        {
            "value": s,
            "label": passphrase_store.SOURCE_LABELS_IT[s],
            "description": passphrase_store.SOURCE_DESCRIPTIONS_IT[s],
            "current": s == pp_source,
        }
        for s in passphrase_store.SOURCES
    ]
    backup_key_file = Path(current_app.instance_path) / "backup.key"
    backup_key_exists = backup_key_file.exists()

    return render_template(
        "settings/backups.html",
        backups=items,
        settings=settings,
        backup_dir=str(backup_service.get_backup_dir()),
        live_db_encrypted=live_db_encrypted,
        sqlcipher_available=db_crypto.is_sqlcipher_available(),
        pp_source=pp_source,
        pp_sources=pp_sources,
        pp_source_prompt=passphrase_store.SOURCE_PROMPT,
        backup_key_exists=backup_key_exists,
    )


@bp.route("/backups/run", methods=["POST"])
@login_required
@admin_required
def backups_run():
    """Create a backup right now, then prune by retention."""
    from stoic_eln.services import backup as backup_service

    try:
        bf = backup_service.create_backup(reason="manual")
        backup_service.prune_old_backups()
        flash(
            _("Backup creato: %(name)s (%(mb).2f MB).", name=bf.filename, mb=bf.size_mb),
            "success",
        )
    except Exception as e:
        flash(_("Backup fallito: %(err)s", err=str(e)), "danger")
    return redirect(url_for("settings.backups"))


@bp.route("/backups/<filename>/download")
@login_required
@admin_required
def backups_download(filename: str):
    """Stream a backup file to the browser as an attachment."""
    from flask import send_from_directory
    from stoic_eln.services import backup as backup_service

    # Defensive: reject path traversal even though Flask's
    # send_from_directory would catch it. Filename must match our
    # convention.
    if backup_service._parse_timestamp(filename) is None:
        abort(404)
    backup_dir = backup_service.get_backup_dir()
    return send_from_directory(
        backup_dir,
        filename,
        as_attachment=True,
        download_name=filename,
    )


@bp.route("/backups/<filename>/restore", methods=["POST"])
@login_required
@admin_required
def backups_restore(filename: str):
    """Restore the live DB from a backup file.

    Requires a confirmation step in the form (a checkbox the user
    must tick), since the operation is destructive. The previous
    live DB is sidelined, not deleted, so a botched restore is
    still recoverable.
    """
    from stoic_eln.services import backup as backup_service

    confirm = request.form.get("confirm") == "yes"
    if not confirm:
        flash(_("Conferma il ripristino spuntando la casella."), "warning")
        return redirect(url_for("settings.backups"))

    if backup_service._parse_timestamp(filename) is None:
        flash(_("Nome file di backup non valido."), "danger")
        return redirect(url_for("settings.backups"))

    try:
        # Take a pre-restore safety backup BEFORE swapping the DB.
        # If anything goes wrong, we have a known-good snapshot of
        # what the live DB looked like just now.
        backup_service.create_backup(reason="pre-restore")
        backup_service.restore_backup(filename)
        flash(
            _(
                "Ripristino effettuato da %(name)s. Riavvia l'applicazione "
                "perché le modifiche abbiano effetto.",
                name=filename,
            ),
            "warning",
        )
    except Exception as e:
        flash(_("Ripristino fallito: %(err)s", err=str(e)), "danger")
    return redirect(url_for("settings.backups"))


@bp.route("/backups/<filename>/delete", methods=["POST"])
@login_required
@admin_required
def backups_delete(filename: str):
    """Delete a single backup file."""
    from stoic_eln.services import backup as backup_service

    if backup_service._parse_timestamp(filename) is None:
        abort(404)
    backup_dir = backup_service.get_backup_dir()
    target = backup_dir / filename
    if not target.exists():
        abort(404)
    try:
        target.unlink()
        log_event(
            action="delete_backup",
            entity_type="backup",
            entity_id=0,
            details={"filename": filename},
        )
        flash(_("Backup %(name)s eliminato.", name=filename), "success")
    except OSError as e:
        flash(_("Impossibile eliminare il backup: %(err)s", err=str(e)), "danger")
    return redirect(url_for("settings.backups"))


@bp.route("/backups/config", methods=["POST"])
@login_required
@admin_required
def backups_config():
    """Update backup configuration (schedule, retention, path)."""
    from stoic_eln.models.settings import AppSetting

    enabled = request.form.get("enabled") == "on"
    AppSetting.set("backup.enabled", "1" if enabled else "0")

    # Numeric fields: validate, fall back to existing or sensible
    # default on bad input rather than refusing the whole form.
    def _set_int(key: str, raw: str | None, lo: int, hi: int) -> None:
        if raw is None or raw.strip() == "":
            return
        try:
            v = int(raw)
        except ValueError:
            return
        v = max(lo, min(hi, v))
        AppSetting.set(key, str(v))

    _set_int("backup.hour", request.form.get("hour"), 0, 23)
    _set_int("backup.minute", request.form.get("minute"), 0, 59)
    _set_int("backup.keep_daily", request.form.get("keep_daily"), 1, 365)
    _set_int("backup.keep_weekly", request.form.get("keep_weekly"), 0, 104)

    path_raw = (request.form.get("path") or "").strip()
    if path_raw:
        AppSetting.set("backup.path", path_raw)

    log_event(
        action="update_backup_config",
        entity_type="settings",
        entity_id=0,
        details={"enabled": enabled},
    )
    flash(
        _(
            "Configurazione backup salvata. Riavvia l'applicazione "
            "per applicare il nuovo orario allo scheduler."
        ),
        "success",
    )
    return redirect(url_for("settings.backups"))


# ── Backup encryption (patch 14.1) ───────────────────────────────


@bp.route("/backups/passphrase", methods=["POST"])
@login_required
@admin_required
def backups_passphrase():
    """Set or change the backup encryption passphrase.

    Writes the passphrase to ``instance/backup.key`` (mode 0600).
    The passphrase is verified with a self-test encrypt+decrypt
    before being persisted, so we never store a broken value.

    Important: changing the passphrase makes existing encrypted
    backups unreadable. The UI shows a clear warning.
    """
    from pathlib import Path

    from stoic_eln.services import backup_crypto
    from flask import current_app

    new_pass = (request.form.get("passphrase") or "").strip()
    confirm = (request.form.get("passphrase_confirm") or "").strip()

    if not new_pass:
        flash(_("La passphrase non può essere vuota."), "danger")
        return redirect(url_for("settings.backups"))

    if new_pass != confirm:
        flash(_("Le due passphrase inserite non coincidono."), "danger")
        return redirect(url_for("settings.backups"))

    if len(new_pass) < 12:
        flash(_("La passphrase deve essere lunga almeno 12 caratteri."), "danger")
        return redirect(url_for("settings.backups"))

    # Self-test: encrypt + decrypt a probe blob with the new
    # passphrase to confirm the crypto stack is functional.
    result = backup_crypto.verify_passphrase(new_pass)
    if not result.ok:
        flash(
            _(
                "Test crittografia fallito: %(err)s. La passphrase non è stata salvata.",
                err=result.error,
            ),
            "danger",
        )
        return redirect(url_for("settings.backups"))

    instance_path = Path(current_app.instance_path)
    backup_crypto.write_passphrase_file(instance_path, new_pass)

    log_event(
        action="set_backup_passphrase",
        entity_type="settings",
        entity_id=0,
        details={"path": str(instance_path / "backup.key")},
    )
    flash(
        _(
            "Passphrase salvata in instance/backup.key. "
            "I prossimi backup saranno cifrati con AES-256-GCM. "
            "ATTENZIONE: conserva la passphrase in un posto sicuro; "
            "se la perdi, i backup cifrati saranno irrecuperabili."
        ),
        "warning",
    )
    return redirect(url_for("settings.backups"))


@bp.route("/backups/passphrase/disable", methods=["POST"])
@login_required
@admin_required
def backups_passphrase_disable():
    """Remove the passphrase file, disabling encryption for future
    backups. Existing encrypted backups remain unreadable without
    the original passphrase."""
    from pathlib import Path

    from flask import current_app

    instance_path = Path(current_app.instance_path)
    key_file = instance_path / "backup.key"
    if not key_file.exists():
        flash(_("Nessuna passphrase configurata."), "info")
        return redirect(url_for("settings.backups"))

    confirm = request.form.get("confirm") == "yes"
    if not confirm:
        flash(_("Conferma la disattivazione spuntando la casella."), "warning")
        return redirect(url_for("settings.backups"))

    key_file.unlink()
    log_event(
        action="disable_backup_encryption",
        entity_type="settings",
        entity_id=0,
        details={},
    )
    flash(
        _(
            "Crittografia disattivata. I prossimi backup saranno in "
            "chiaro. I backup cifrati esistenti rimangono cifrati."
        ),
        "warning",
    )
    return redirect(url_for("settings.backups"))


# ── Passphrase source (patch 14.3) ───────────────────────────────


@bp.route("/backups/passphrase-source", methods=["POST"])
@login_required
@admin_required
def backups_passphrase_source():
    """Change which backend Stoic uses to obtain the passphrase
    at boot: ``prompt``, ``file``, or ``env``.

    Effects are not immediate: the running process keeps using
    the source it booted with. The new value is persisted both to
    AppSetting (for the UI display) and to the on-disk marker
    ``instance/auth_source`` (which the next boot reads before
    the DB is open).

    Switching to ``prompt`` mode while a ``backup.key`` file
    exists does NOT delete the file — that's an explicit action
    the admin can take separately. Keeping it lying around defeats
    the purpose of ``prompt`` mode, but it's the admin's call.
    """
    from stoic_eln.services import passphrase_store

    new_source = (request.form.get("source") or "").strip()
    if new_source not in passphrase_store.SOURCES:
        flash(_("Sorgente non valida."), "danger")
        return redirect(url_for("settings.backups"))

    try:
        passphrase_store.set_source(new_source)
    except ValueError as e:
        flash(_("Errore: %(err)s", err=str(e)), "danger")
        return redirect(url_for("settings.backups"))

    log_event(
        action="set_passphrase_source",
        entity_type="settings",
        entity_id=0,
        details={"source": new_source},
    )

    msg = _(
        "Sorgente passphrase impostata su '%(s)s'. "
        "Il cambio è attivo dal prossimo riavvio di Stoic.",
        s=new_source,
    )
    if new_source == passphrase_store.SOURCE_PROMPT:
        msg += " " + _(
            "Da ora in poi Stoic ti chiederà la passphrase a ogni "
            "avvio. Se hai ancora il file instance/backup.key, "
            "considera di eliminarlo manualmente (altrimenti la "
            "sicurezza extra del modo 'prompt' è inutile)."
        )
    flash(msg, "warning")
    return redirect(url_for("settings.backups"))


@bp.route("/backups/passphrase-key-delete", methods=["POST"])
@login_required
@admin_required
def backups_passphrase_key_delete():
    """Delete instance/backup.key after the user explicitly
    confirms. Used by the 'prompt' mode transition flow.
    """
    from pathlib import Path
    from flask import current_app

    confirm = request.form.get("confirm") == "yes"
    if not confirm:
        flash(_("Conferma l'eliminazione spuntando la casella."), "warning")
        return redirect(url_for("settings.backups"))

    key_file = Path(current_app.instance_path) / "backup.key"
    if not key_file.exists():
        flash(_("Nessun file backup.key da eliminare."), "info")
        return redirect(url_for("settings.backups"))

    try:
        key_file.unlink()
        log_event(
            action="delete_backup_key_file",
            entity_type="settings",
            entity_id=0,
            details={},
        )
        flash(
            _(
                "File instance/backup.key eliminato. "
                "La passphrase ora esiste solo nella tua testa "
                "(e in RAM mentre Stoic gira)."
            ),
            "success",
        )
    except OSError as e:
        flash(_("Impossibile eliminare il file: %(err)s", err=str(e)), "danger")
    return redirect(url_for("settings.backups"))
