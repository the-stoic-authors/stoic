"""Stoic ELN — Authentication routes."""

from __future__ import annotations

from datetime import datetime, UTC

from flask import (
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import gettext as _
from flask_login import current_user, login_required, login_user, logout_user
from urllib.parse import urlparse

from stoic_eln.blueprints.auth import bp
from stoic_eln.blueprints.auth.forms import ChangePasswordForm, LoginForm
from stoic_eln.extensions import db
from stoic_eln.models.user import User
from stoic_eln.services.audit import log_event


def _is_safe_url(target: str) -> bool:
    """Reject open-redirect attempts."""
    if not target:
        return False
    parsed = urlparse(target)
    return parsed.netloc == "" and parsed.scheme == ""


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.query(User).filter_by(username=form.username.data).first()

        if user is None or not user.check_password(form.password.data):
            log_event(
                action="login_failed",
                entity_type="user",
                details={"username": form.username.data},
                user_id=None,
            )
            flash(_("Username o password non corretti."), "danger")
            return render_template("auth/login.html", form=form), 401

        if not user.is_active:
            log_event(
                action="login_failed",
                entity_type="user",
                entity_id=user.id,
                details={"reason": "inactive"},
                user_id=None,
            )
            flash(_("Il tuo account non è attivo. Contatta un amministratore."), "warning")
            return render_template("auth/login.html", form=form), 403

        # Update password hash if needed (Argon2 parameters changed)
        if user.needs_rehash():
            user.set_password(form.password.data)

        user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
        db.session.commit()

        login_user(user, remember=form.remember_me.data)
        log_event(action="login", entity_type="user", entity_id=user.id, user_id=user.id)

        next_page = request.args.get("next")
        if next_page and _is_safe_url(next_page):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    user_id = current_user.id
    log_event(action="logout", entity_type="user", entity_id=user_id, user_id=user_id)
    logout_user()
    flash(_("Sei stato disconnesso."), "info")
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash(_("La password attuale non è corretta."), "danger")
            return render_template("auth/change_password.html", form=form), 400

        current_user.set_password(form.new_password.data)
        db.session.commit()
        log_event(
            action="update",
            entity_type="user",
            entity_id=current_user.id,
            details={"field": "password"},
        )
        flash(_("Password aggiornata correttamente."), "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/change_password.html", form=form)


@bp.route("/locale/<lang>")
def set_locale(lang: str):
    """Switch the UI locale (for both authenticated and anonymous users)."""
    if lang not in ("it", "en"):
        lang = current_app.config.get("DEFAULT_LOCALE", "it")

    if current_user.is_authenticated:
        current_user.locale = lang
        db.session.commit()
        log_event(
            action="update",
            entity_type="user",
            entity_id=current_user.id,
            details={"field": "locale", "value": lang},
        )

    next_page = request.referrer or url_for("main.dashboard")
    response = make_response(redirect(next_page))
    response.set_cookie("locale", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


@bp.route("/theme/<theme>")
def set_theme(theme: str):
    """Switch the UI theme."""
    if theme not in ("system", "light", "dark"):
        theme = "system"

    if current_user.is_authenticated:
        current_user.theme = theme
        db.session.commit()

    next_page = request.referrer or url_for("main.dashboard")
    response = make_response(redirect(next_page))
    response.set_cookie("theme", theme, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response
