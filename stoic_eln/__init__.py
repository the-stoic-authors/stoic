"""Stoic ELN — application factory.

Copyright (C) 2026 The Stoic Authors

This program is free software: you can redistribute it and/or
modify it under the terms of the GNU Affero General Public License
as published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public
License along with this program. If not, see
<https://www.gnu.org/licenses/agpl-3.0.html>.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import func

from stoic_eln.config import Config, DevelopmentConfig, ProductionConfig, TestingConfig
from stoic_eln.extensions import babel, csrf, db, login_manager, migrate

__version__ = "1.2.1"

CONFIG_MAP: dict[str, type[Config]] = {
    "debug": DevelopmentConfig,
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def create_app(
    config_class: type[Config] | None = None,
    instance_path: str | None = None,
    start_scheduler: bool = True,
) -> Flask:
    """Create and configure a Flask application instance.

    Args:
        config_class: A specific config class, or None to read from FLASK_ENV.
        instance_path: Override Flask's default instance directory. Useful
            for tests that need an isolated location for files like
            ``backup.key`` and ``auth_source``. When None (production),
            Flask computes it from the package location.
        start_scheduler: Whether to start the in-process background
            scheduler (nightly backup, etc.). Default True so that
            ``flask run`` and one-shot scripts continue to schedule
            their own backups. Set to False from ``wsgi.py`` so that
            in a multi-worker gunicorn setup only ONE process runs
            the scheduler (the master, via gunicorn's when_ready hook).
            Tests bypass scheduling regardless of this flag via the
            ``TESTING`` check inside ``init_scheduler``.
    """
    app = Flask(
        __name__,
        instance_relative_config=False,
        template_folder="templates",
        static_folder="static",
        instance_path=instance_path,
    )

    if config_class is None:
        env = os.environ.get("FLASK_ENV", "debug").lower()
        config_class = CONFIG_MAP.get(env, DevelopmentConfig)

    app.config.from_object(config_class)
    config_class.init_app(app)

    # Trust X-Forwarded-* headers from ONE reverse proxy hop (Caddy,
    # nginx). Without this, behind a proxy Flask sees every request
    # as plain HTTP from the proxy's IP: request.is_secure is False,
    # url_for(_external=True) generates http:// URLs (breaking the
    # PWA manifest and absolute redirects), and request.remote_addr
    # logs the proxy container instead of the client.
    #
    # With no proxy in front the headers are absent and ProxyFix is
    # a no-op, so this is safe for `flask run` development too.
    # x_for/x_proto/x_host = 1 means "trust exactly one hop" —
    # a client can't spoof these headers past a correctly configured
    # proxy that overwrites them.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _configure_logging(app)
    _register_extensions(app)
    _register_blueprints(app)
    _register_template_context(app)
    _register_error_handlers(app)
    _register_cli(app)
    _register_onboarding_redirect(app)

    # Ensure schema is up to date (idempotent — creates only missing tables).
    # SQLAlchemy's create_all() looks at metadata.tables and creates anything
    # not yet in the DB, so existing tables and data are untouched. This
    # protects against the case where a new patch adds a model: without
    # this call, the user would have to remember to run `flask init-db`
    # or some migration step. (Settimana 6 patch 9.1)
    _ensure_schema(app)

    # Start the background scheduler (nightly backup job). Skipped
    # under TESTING and when BACKUP_SCHEDULER_DISABLED is set, so
    # the test suite stays deterministic. (Settimana 6 patch 14.0)
    #
    # In a multi-worker gunicorn deployment, ``wsgi.py`` passes
    # ``start_scheduler=False`` so the workers DON'T each spawn
    # their own scheduler — the master process runs exactly one
    # instance via the ``when_ready`` hook in ``gunicorn.conf.py``.
    if start_scheduler:
        from stoic_eln.services.scheduler import init_scheduler

        init_scheduler(app)

    return app


def _ensure_schema(app: Flask) -> None:
    """Create any missing tables. Idempotent and safe on existing DBs."""
    # Importing the models package triggers all model class registrations
    # against db.metadata, so create_all() sees them.
    from stoic_eln import models  # noqa: F401

    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            app.logger.warning("Could not auto-create tables on startup: %s", e)


def _configure_logging(app: Flask) -> None:
    level = app.config.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    app.logger.info("Stoic v%s starting (env=%s)", __version__, app.config.get("ENV"))


def _register_extensions(app: Flask) -> None:
    # Live DB encryption (Settimana 6 patch 14.2): if the DB file
    # on disk looks SQLCipher-encrypted, swap in a sqlcipher3-based
    # connection factory before initialising Flask-SQLAlchemy. The
    # detection is a 16-byte sniff on the live DB file, robust
    # because plain SQLite files always start with a known magic
    # string. Skipped for non-SQLite URIs and :memory: databases.
    _maybe_enable_sqlcipher(app)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    babel.init_app(app, locale_selector=_select_locale)

    # User loader for Flask-Login (deferred import to avoid circular)
    from stoic_eln.models.user import User

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        return db.session.get(User, int(user_id))


def _maybe_enable_sqlcipher(app: Flask) -> None:
    """If the live DB is SQLCipher-encrypted, configure
    SQLAlchemy to use sqlcipher3 with the configured passphrase.

    Skipped in ``TESTING`` mode: tests use :memory: or short-lived
    file DBs that don't need encryption, and the source-marker
    machinery would otherwise pollute the dev ``instance/`` dir.
    Tests that specifically exercise encryption manage SQLCipher
    setup themselves.

    Boot-time flow (production):

      1. If the DB file looks encrypted, walk the configured
         passphrase source(s) — ``prompt``, ``file``, or ``env``,
         depending on ``AppSetting.auth.passphrase_source`` (or
         the on-disk marker ``instance/auth_source`` for the
         pre-DB phase).
      2. Validate the candidate passphrase by trying to open the
         DB once. Wrong passphrase → in ``prompt`` mode the user
         is reprompted; in ``file``/``env`` modes we surface a
         clear error and refuse to boot.
      3. If validation passes, install a SQLAlchemy ``creator``
         that opens new connections with sqlcipher3 + PRAGMA key.

    The first-time-ever migration is handled by
    ``ensure_default_source_setting``: existing 14.1/14.2 installs
    that already had a ``backup.key`` keep working in ``file``
    mode; new installs default to ``none`` (no encryption — the
    user opts in explicitly from Settings → Backup).
    """
    # Skipped in ``TESTING`` mode unless the test explicitly opts
    # in by setting ``SQLCIPHER_TEST_ENABLE = True`` in the config.
    # Most tests use :memory: or short-lived plain file DBs that
    # don't need encryption, and would only be confused by it; the
    # specific 14.2/14.3 tests that exercise SQLCipher boot
    # integration set the flag in their fixture.
    if app.config.get("TESTING") and not app.config.get("SQLCIPHER_TEST_ENABLE"):
        return

    from stoic_eln.services import db_crypto, passphrase_store

    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite:///"):
        return
    db_path_str = uri[len("sqlite:///") :]
    if db_path_str == ":memory:" or db_path_str.startswith(":memory:"):
        return

    db_path = Path(db_path_str)
    instance_path = Path(app.instance_path)

    # Initialise (or migrate) the source marker on every boot.
    # No-op if a valid marker already exists.
    try:
        passphrase_store.ensure_default_source_setting(instance_path)
    except Exception as e:
        app.logger.warning("could not initialise passphrase source: %s", e)

    if not db_crypto.is_encrypted_db(db_path):
        return  # Plain DB, nothing to do

    if not db_crypto.is_sqlcipher_available():
        app.logger.error(
            "Live DB at %s is SQLCipher-encrypted but sqlcipher3 is not "
            "installed. Run: pip install sqlcipher3-wheels",
            db_path,
        )
        return

    # Verifier: opens the encrypted DB with a candidate passphrase
    # and returns True iff it succeeds. Lets `prompt` mode retry
    # on a wrong entry, and lets `file`/`env` modes fail fast with
    # a clear message instead of crashing on first SQLAlchemy
    # query later.
    def _verify(pp: str) -> bool:
        try:
            import sqlcipher3

            conn = sqlcipher3.connect(str(db_path))
            safe = pp.replace("'", "''")
            conn.execute(f"PRAGMA key='{safe}'")
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            conn.close()
            return True
        except Exception:
            return False

    # Push an app context so passphrase_store.current_source() can
    # call current_app.instance_path. This hook runs inside
    # _register_extensions, BEFORE Flask has an active context, so
    # without this push the marker-file fallback would silently no-op
    # (it depends on current_app.instance_path).
    with app.app_context():
        try:
            passphrase = passphrase_store.get_passphrase(
                instance_path,
                verifier=_verify,
            )
        except passphrase_store.PassphraseUnavailable as e:
            app.logger.error("Cannot resolve passphrase for encrypted DB: %s", e)
            return

        if not passphrase:
            app.logger.error(
                "Live DB at %s is SQLCipher-encrypted, but no passphrase "
                "was obtained from the configured source (%s).",
                db_path,
                passphrase_store.current_source(),
            )
            return

        creator = db_crypto.make_sqlcipher_creator(str(db_path), passphrase)
        # Merge with any existing engine options the user configured.
        opts = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
        opts["creator"] = creator
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = opts
        app.logger.info(
            "SQLCipher enabled for live DB at %s (source=%s)",
            db_path,
            passphrase_store.current_source(),
        )


def _select_locale() -> str:
    """Determine which locale to use for the current request.

    Order:
      1. Logged-in user preference (User.locale)
      2. Cookie 'locale' (set by language switcher for anonymous users)
      3. Browser Accept-Language header
      4. Default locale from config
    """
    from flask import current_app, has_request_context, request
    from flask_login import current_user

    default = current_app.config.get("DEFAULT_LOCALE", "it")

    # Outside a request (PDF/background generation, scheduled jobs) there is
    # no user or headers to read — fall back to the default locale instead
    # of dereferencing an unbound current_user.
    if not has_request_context():
        return default

    try:
        if current_user.is_authenticated and current_user.locale:
            return current_user.locale
    except Exception:
        pass

    cookie_locale = request.cookies.get("locale")
    if cookie_locale in ("it", "en"):
        return cookie_locale

    best = request.accept_languages.best_match(["it", "en"])
    if best:
        return best

    return default


def _register_blueprints(app: Flask) -> None:
    from stoic_eln.blueprints.attachments import bp as attachments_bp
    from stoic_eln.blueprints.auth import bp as auth_bp
    from stoic_eln.blueprints.docs import bp as docs_bp
    from stoic_eln.blueprints.inventory import bp as inventory_bp
    from stoic_eln.blueprints.main import bp as main_bp
    from stoic_eln.blueprints.mixtures import bp as mixtures_bp
    from stoic_eln.blueprints.notes import bp as notes_bp
    from stoic_eln.blueprints.onboarding import bp as onboarding_bp
    from stoic_eln.blueprints.orders import bp as orders_bp
    from stoic_eln.blueprints.preps import bp as preps_bp
    from stoic_eln.blueprints.procedures import bp as procedures_bp
    from stoic_eln.blueprints.reactions import bp as reactions_bp
    from stoic_eln.blueprints.reports import bp as reports_bp
    from stoic_eln.blueprints.runs import bp as runs_bp
    from stoic_eln.blueprints.search import bp as search_bp
    from stoic_eln.blueprints.settings import bp as settings_bp
    from stoic_eln.blueprints.substances import bp as substances_bp
    from stoic_eln.blueprints.suppliers import bp as suppliers_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(substances_bp)
    app.register_blueprint(mixtures_bp)
    app.register_blueprint(preps_bp)
    app.register_blueprint(procedures_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(reactions_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(attachments_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(onboarding_bp)


def _register_onboarding_redirect(app: Flask) -> None:
    """Redirect admins to the onboarding wizard at login until they
    complete it.

    The hook is global but narrow:
      - Triggers only for authenticated admin users.
      - Skips static, auth endpoints, the onboarding blueprint itself,
        and tool endpoints that may run via HTMX during onboarding.
      - Reads the completion flag from AppSetting; if reading raises
        (e.g. very early boot, missing table), it stays silent and
        does not redirect. The wizard must never break the app.

    Non-admin users and unauthenticated requests pass through.
    """
    from flask import redirect, request, url_for
    from flask_login import current_user

    @app.before_request
    def _maybe_redirect_to_onboarding():
        # Only authenticated admins
        try:
            if not current_user.is_authenticated:
                return None
            if not getattr(current_user, "is_admin", False):
                return None
        except Exception:
            return None

        # Skip routes that shouldn't trigger the redirect:
        #   - the onboarding blueprint itself
        #   - auth (so logout still works)
        #   - static files
        #   - HTMX/XHR requests, which may be widgets on the dashboard
        endpoint = request.endpoint or ""
        if endpoint.startswith("onboarding."):
            return None
        if endpoint.startswith("auth."):
            return None
        if endpoint == "static":
            return None
        if request.headers.get("HX-Request"):
            return None

        # Check completion flag — silent on errors so onboarding
        # never breaks the rest of the app.
        try:
            from stoic_eln.blueprints.onboarding.routes import is_completed

            if is_completed():
                return None
        except Exception:
            return None

        return redirect(url_for("onboarding.index"))


def _register_template_context(app: Flask) -> None:
    """Inject globals into all templates."""

    # Register unit-formatting helpers as Jinja globals so templates
    # can render best-fit mass/volume strings inline.
    from stoic_eln.services import units as _units

    app.jinja_env.globals["best_fit_mass"] = _units.best_fit_mass
    app.jinja_env.globals["best_fit_volume"] = _units.best_fit_volume

    from stoic_eln.services import step_calc as _step_calc

    app.jinja_env.globals["compute_run_step_component"] = _step_calc.compute_run_step_component

    # Currency configuration (Settimana 6 patch 6.1) — `format_currency`
    # available as a global, and `|currency` as a filter, so templates
    # can simply write `{{ amount|currency }}` instead of hardcoding "€".
    from stoic_eln.services import currency as _currency

    app.jinja_env.globals["format_currency"] = _currency.format_currency
    app.jinja_env.globals["currency_glyph"] = _currency.currency_glyph

    def _currency_filter(amount, decimals=2):
        return _currency.format_currency(amount, decimals=decimals)

    app.jinja_env.filters["currency"] = _currency_filter

    # Markdown rendering for note bodies (Settimana 6 patch 9)
    from stoic_eln.services import markdown as _markdown

    app.jinja_env.filters["markdown"] = _markdown.render_markdown

    @app.context_processor
    def inject_globals() -> dict:
        from flask import request
        from flask_babel import get_locale
        from flask_login import current_user

        # Determine current theme: user pref > cookie > config default
        theme = "system"
        if current_user.is_authenticated and getattr(current_user, "theme", None):
            theme = current_user.theme
        else:
            cookie_theme = request.cookies.get("theme")
            if cookie_theme in ("system", "light", "dark"):
                theme = cookie_theme
            else:
                theme = app.config.get("DEFAULT_THEME", "system")

        # Lab name: prefer the value set via the onboarding wizard
        # or settings page (AppSetting "lab.name"), fall back to the
        # config LAB_NAME, then to the default "Stoic". Reading from
        # AppSetting is wrapped in a try/except because the table
        # may not exist yet (e.g. during very early app boot or in
        # tests with a clean schema).
        try:
            from stoic_eln.blueprints.onboarding.routes import get_lab_name

            lab_name = get_lab_name(default=app.config.get("LAB_NAME", "Stoic"))
        except Exception:
            lab_name = app.config.get("LAB_NAME", "Stoic")

        return {
            "app_version": __version__,
            "lab_name": lab_name,
            "current_theme": theme,
            "get_locale": get_locale,
            "substances_for_picker": _substances_for_picker,
            "mixtures_for_picker": _mixtures_for_picker,
            "step_quantity": _step_quantity,
            "available_locales": [
                ("it", "Italiano"),
                ("en", "English"),
            ],
        }


def _substances_for_picker():
    """Helper exposed to templates: returns active substances ordered by name.

    Used by the reaction component picker. Kept simple for now; if catalogue
    grows large we'll switch to a search-as-you-type widget.
    """
    from stoic_eln.extensions import db
    from stoic_eln.models.substance import Substance

    return (
        db.session.query(Substance)
        .filter(Substance.is_active.is_(True))
        .order_by(func.lower(Substance.name).asc())
        .all()
    )


def _mixtures_for_picker():
    """Active mixtures ordered by name — same shape as substances picker.

    Used by the reaction component picker when "Miscela" is selected
    (patch 13.5). Like _substances_for_picker, kept simple for now;
    if mixture catalogue grows large we'll switch to autocomplete.
    """
    from stoic_eln.extensions import db
    from stoic_eln.models.mixture import Mixture

    return (
        db.session.query(Mixture)
        .filter(Mixture.is_active.is_(True))
        .order_by(func.lower(Mixture.name).asc())
        .all()
    )


def _step_quantity(sc, step, reaction):
    """Compute display quantities (g, mL, mmol) for a step component.

    Resolves the reference component (limiting reagent or explicit), uses
    the reaction's default_scale_mmol, and applies the step component's
    ratio_kind + ratio_value to derive absolute quantities.

    Returns a plain dict with keys 'g', 'mL', 'mmol' — values may be None
    if not computable from the available data.

    Mixture-backed step components (patch 13.6):
      * ``ratio_kind='free'`` (chromatography eluent etc.) → returns
        all None so the template can render "ad libitum"
      * Otherwise uses the mixture's primary solute as the substance
        reference for MW / density. For a typical eluent that lookup
        is fine (the bulk solvent dominates volumes).
    """
    from stoic_eln.services.step_calc import (
        compute_step_component,
        reference_quantities,
    )

    # Free-volume marker: nothing to compute at template time. The
    # template just shows "—" or "ad libitum" and the Run records
    # the actual volume.
    if sc.ratio_kind == "free":
        return {"g": None, "mL": None, "mmol": None}

    # Free entries (P2): non-inventory lines with a free unit label.
    if getattr(sc, "free_name", None):
        if sc.ratio_kind == "fixed_value":
            return {"g": None, "mL": None, "mmol": None, "free": sc.ratio_value}
        if sc.ratio_kind == "column_diameter_mm":
            # Geometry from the stationary phase in the SAME step:
            # find it, get its computed mass, derive the diameter.
            from stoic_eln.services.step_calc import compute_column_diameter_mm

            silica = next((c for c in step.components if c.role == "stationary_phase"), None)
            if silica is None:
                return {"g": None, "mL": None, "mmol": None, "free": None}
            silica_qty = _step_quantity(silica, step, reaction)
            d = compute_column_diameter_mm(silica_qty.get("g"), sc.ratio_value)
            return {"g": None, "mL": None, "mmol": None, "free": d}
        return {"g": None, "mL": None, "mmol": None, "free": None}

    # Resolve reference
    if step.reference_component_id and step.reference_component is not None:
        ref = step.reference_component
    else:
        ref = reaction.limiting_component

    if ref is None or sc.ratio_value is None:
        return {"g": None, "mL": None, "mmol": None}

    # Reference component might be mixture-backed (post-13.5).
    # effective_substance falls back to the primary solute for that case.
    ref_sub = getattr(ref, "effective_substance", None) or ref.substance
    if ref_sub is None:
        return {"g": None, "mL": None, "mmol": None}

    scale = reaction.default_scale_mmol or 1.0
    ref_eq = ref.equivalents or 1.0

    ref_qty = reference_quantities(
        ref_equivalents=ref_eq,
        scale_mmol=scale,
        ref_mw=ref_sub.molecular_weight,
        ref_density=ref_sub.density,
    )

    # Substance behind the step component (could be a mixture's solute)
    sc_sub = getattr(sc, "substance", None)
    if sc_sub is None and sc.mixture is not None:
        for mc in sc.mixture.components:
            if mc.role == "solute" and mc.substance is not None:
                sc_sub = mc.substance
                break

    qty = compute_step_component(
        ratio_kind=sc.ratio_kind,
        ratio_value=sc.ratio_value,
        ref_quantity=ref_qty,
        sub_mw=sc_sub.molecular_weight if sc_sub else None,
        sub_density=sc_sub.density if sc_sub else None,
    )

    return {"g": qty.g, "mL": qty.mL, "mmol": qty.mmol}


def _register_error_handlers(app: Flask) -> None:
    from flask import render_template

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(_e):
        db.session.rollback()
        return render_template("errors/500.html"), 500


def _register_cli(app: Flask) -> None:
    """Register custom CLI commands."""
    import click

    @app.cli.command("init-db")
    @click.option("--admin-password", default="admin123", help="Initial admin password")
    @click.option("--no-seed", is_flag=True, help="Skip seed data")
    def init_db_command(admin_password: str, no_seed: bool) -> None:
        """Initialize the database with schema, admin user, and seed data."""
        from stoic_eln.models.user import User
        from stoic_eln.seeds.loader import seed_all
        from stoic_eln.services.audit import log_event

        db.create_all()

        # Create admin user if doesn't exist
        if db.session.query(User).filter_by(username="admin").first() is None:
            admin = User(
                username="admin",
                full_name="Amministratore",
                operator_code="ADM",
                is_admin=True,
                is_active=True,
                locale="it",
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            log_event(action="create", entity_type="user", entity_id=admin.id, user_id=None)
            click.echo(f"Created admin user: admin / {admin_password}")
            click.echo("Change this password immediately after first login!")
        else:
            click.echo("Admin user already exists.")

        if not no_seed:
            click.echo("Loading seed data (hazard phrases + starter substances)...")
            results = seed_all()
            for label, (added, skipped) in results.items():
                click.echo(f"  {label}: added={added} skipped={skipped}")

        click.echo("Database initialized.")

    @app.cli.command("ensure-schema")
    def ensure_schema_command() -> None:
        """Create any missing tables on an existing database.

        Use this after applying a patch that adds new tables (e.g. ``note``,
        ``attachment``, ...) when ``make run`` doesn't auto-create them
        for some reason.

        Idempotent: existing tables are left untouched.
        """
        from sqlalchemy import inspect as sa_inspect

        from stoic_eln import models  # noqa: F401  — register all metadata

        before = set(sa_inspect(db.engine).get_table_names())
        db.create_all()
        after = set(sa_inspect(db.engine).get_table_names())
        added = sorted(after - before)
        if added:
            click.echo(f"Created {len(added)} table(s): {', '.join(added)}")
        else:
            click.echo("No missing tables. Schema is up to date.")

    @app.cli.command("create-user")
    @click.argument("username")
    @click.argument("full_name")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option("--admin", is_flag=True, default=False)
    def create_user_command(username: str, full_name: str, password: str, admin: bool) -> None:
        """Create a new user."""
        from stoic_eln.models.user import User

        if db.session.query(User).filter_by(username=username).first():
            click.echo(f"User '{username}' already exists.", err=True)
            return

        user = User(
            username=username,
            full_name=full_name,
            is_admin=admin,
            is_active=True,
            locale="it",
        )
        user.set_password(password)
        # operator_code auto-generated from initials
        from stoic_eln.services.code_generator import generate_operator_code

        user.operator_code = generate_operator_code(full_name)
        db.session.add(user)
        db.session.commit()
        click.echo(f"User '{username}' created with operator_code '{user.operator_code}'.")

    @app.cli.command("backup")
    @click.option("--reason", default="cli", help="Tag stored in the audit log (default: 'cli').")
    @click.option(
        "--no-prune", is_flag=True, help="Skip pruning by retention policy after the backup."
    )
    def backup_command(reason: str, no_prune: bool) -> None:
        """Run a database backup right now (atomic, gzipped).

        Useful before risky operations (DB resets, migrations, schema
        changes). Equivalent to clicking 'Esegui backup ora' in
        /settings/backups.
        """
        from stoic_eln.services import backup as backup_service

        try:
            bf = backup_service.create_backup(reason=reason)
            click.echo(f"Created: {bf.filename} ({bf.size_mb:.2f} MB)")
            if not no_prune:
                deleted = backup_service.prune_old_backups()
                if deleted:
                    click.echo(f"Pruned {len(deleted)} old backup(s).")
        except Exception as e:
            click.echo(f"Backup failed: {e}", err=True)
            raise click.Abort() from e

    @app.cli.command("backups-list")
    def backups_list_command() -> None:
        """List existing backup files, newest first."""
        from stoic_eln.services import backup as backup_service

        items = backup_service.list_backups()
        if not items:
            click.echo("(no backups)")
            return
        for b in items:
            tag = "[ENC]" if b.encrypted else "     "
            click.echo(
                f"{b.timestamp.strftime('%Y-%m-%d %H:%M:%S')}  "
                f"{tag} {b.size_mb:>7.2f} MB  {b.filename}"
            )

    @app.cli.command("backup-set-passphrase")
    @click.option(
        "--passphrase",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="The new passphrase (will be prompted if omitted).",
    )
    def backup_set_passphrase_command(passphrase: str) -> None:
        """Set or change the backup encryption passphrase.

        Stores the passphrase in ``instance/backup.key`` (mode 0600).
        After this, all new backups will be AES-256-GCM encrypted.

        IMPORTANT: changing the passphrase makes existing encrypted
        backups unreadable with the new key. Keep your old
        passphrase if you have old encrypted backups to restore.
        """
        from stoic_eln.services import backup_crypto

        if len(passphrase.strip()) < 12:
            click.echo("Passphrase must be at least 12 characters.", err=True)
            raise click.Abort()

        result = backup_crypto.verify_passphrase(passphrase)
        if not result.ok:
            click.echo(f"Crypto self-test failed: {result.error}", err=True)
            raise click.Abort()

        path = backup_crypto.write_passphrase_file(
            Path(app.instance_path),
            passphrase,
        )
        click.echo(f"Passphrase saved to {path}.")
        click.echo("Future backups will be encrypted.")
        click.echo("WARNING: store the passphrase somewhere safe.")
        click.echo("Losing it makes the encrypted backups irrecoverable.")

    @app.cli.command("db-encrypt")
    @click.option("--skip-backup", is_flag=True, help="Skip the safety backup. Not recommended.")
    @click.confirmation_option(
        prompt="This will encrypt your live database with SQLCipher. "
        "Make sure Stoic is NOT running. Continue?"
    )
    def db_encrypt_command(skip_backup: bool) -> None:
        """Encrypt the live database with SQLCipher (Settimana 6 patch 14.2).

        Steps:
          1. Verify a passphrase is configured (file or env var)
          2. Create a safety backup (skip with --skip-backup)
          3. Run sqlcipher_export to write an encrypted copy
          4. Sideline the plain DB to <name>.pre-encrypt-<ts>.db
          5. Install the encrypted copy at the original path

        Stoic MUST NOT be running during this operation. The CLI
        connects directly to the file; if Stoic holds an open WAL,
        the export will fail (which is the safer outcome).

        Idempotent: running on an already-encrypted DB is a no-op
        if the passphrase matches.
        """
        from stoic_eln.services import backup as bkp
        from stoic_eln.services import backup_crypto, db_crypto

        passphrase = backup_crypto.resolve_passphrase(Path(app.instance_path))
        if not passphrase:
            click.echo(
                "No passphrase configured. Run 'flask backup-set-passphrase' "
                "first, or set STOIC_BACKUP_PASSPHRASE.",
                err=True,
            )
            raise click.Abort()

        if not db_crypto.is_sqlcipher_available():
            click.echo(
                "sqlcipher3 is not installed. Run:\n  pip install sqlcipher3-wheels",
                err=True,
            )
            raise click.Abort()

        # Safety backup (unless explicitly skipped). This goes
        # through the normal backup pipeline so it ends up in the
        # configured backup dir with retention.
        if not skip_backup:
            try:
                bf = bkp.create_backup(reason="pre-db-encrypt")
                click.echo(f"Safety backup: {bf.filename} ({bf.size_mb:.2f} MB)")
            except Exception as e:
                click.echo(f"Safety backup failed: {e}", err=True)
                click.echo("Aborting. Re-run with --skip-backup to override.", err=True)
                raise click.Abort() from e
        else:
            click.echo("(skipping safety backup as requested)")

        db_path = Path(app.config["SQLALCHEMY_DATABASE_URI"][len("sqlite:///") :])
        result = db_crypto.encrypt_db(db_path, passphrase)
        if not result.ok:
            click.echo(f"Encryption failed: {result.error}", err=True)
            raise click.Abort()

        if result.sidelined_path is None:
            click.echo(result.error or "DB already encrypted.")
            return

        click.echo(f"DB encrypted in place: {db_path}")
        click.echo(f"  {result.table_count} tables exported")
        click.echo(f"  Original sidelined: {result.sidelined_path.name}")
        click.echo("")
        click.echo("Restart Stoic — it will pick up SQLCipher automatically.")

    @app.cli.command("db-decrypt")
    @click.confirmation_option(
        prompt="This will DECRYPT your live database to plain SQLite. "
        "Stoic must not be running. Continue?"
    )
    def db_decrypt_command() -> None:
        """Decrypt the live database back to plain SQLite.

        Inverse of db-encrypt. Use this if you decide SQLCipher is
        not for you, or to migrate the DB to a setup without it.

        Idempotent: running on an already-plain DB is a no-op.
        """
        from stoic_eln.services import backup_crypto, db_crypto

        passphrase = backup_crypto.resolve_passphrase(Path(app.instance_path))
        if not passphrase:
            click.echo("No passphrase configured.", err=True)
            raise click.Abort()

        db_path = Path(app.config["SQLALCHEMY_DATABASE_URI"][len("sqlite:///") :])
        result = db_crypto.decrypt_db(db_path, passphrase)
        if not result.ok:
            click.echo(f"Decryption failed: {result.error}", err=True)
            raise click.Abort()

        if result.sidelined_path is None:
            click.echo(result.error or "DB already plain.")
            return

        click.echo(f"DB decrypted in place: {db_path}")
        click.echo(f"  {result.table_count} tables")
        click.echo(f"  Original (encrypted) sidelined: {result.sidelined_path.name}")

    @app.cli.command("db-status")
    def db_status_command() -> None:
        """Show whether the live DB is plain or SQLCipher-encrypted."""
        from stoic_eln.services import backup_crypto, db_crypto

        db_path = Path(app.config["SQLALCHEMY_DATABASE_URI"][len("sqlite:///") :])
        if not db_path.exists():
            click.echo(f"DB file not found: {db_path}")
            return

        encrypted = db_crypto.is_encrypted_db(db_path)
        passphrase = backup_crypto.resolve_passphrase(Path(app.instance_path))
        size_mb = db_path.stat().st_size / (1024 * 1024)

        click.echo(f"DB:         {db_path}")
        click.echo(f"Size:       {size_mb:.2f} MB")
        click.echo(f"Encrypted:  {'yes (SQLCipher)' if encrypted else 'no (plain SQLite)'}")
        click.echo(f"Passphrase: {'configured' if passphrase else 'NOT configured'}")
        click.echo(
            f"sqlcipher3: {'installed' if db_crypto.is_sqlcipher_available() else 'NOT installed'}"
        )
        if encrypted and not passphrase:
            click.echo("\nWARNING: DB is encrypted but no passphrase is configured.")
            click.echo("         Stoic will fail to start.")

    @app.cli.command("passphrase-test")
    def passphrase_test_command() -> None:
        """Test the configured passphrase source without booting Stoic.

        Walks the same code path the boot uses, reports which
        source was tried, whether it produced a value, and whether
        that value opens the encrypted DB (if encrypted).

        Useful for debugging deployment setups: "did my systemd
        Environment= line actually reach the process?", "is the
        prompt mode working over SSH?", etc.
        """
        from stoic_eln.services import db_crypto, passphrase_store

        # Force re-resolution: clear cache so we actually exercise
        # the source rather than returning a value possibly set
        # earlier in the same Python process.
        passphrase_store.reset_cache()

        source = passphrase_store.current_source()
        click.echo(f"Configured source: {source}")
        click.echo("")

        instance_path = Path(app.instance_path)
        db_path_str = app.config["SQLALCHEMY_DATABASE_URI"][len("sqlite:///") :]
        db_path = Path(db_path_str)
        db_is_encrypted = db_path.exists() and db_crypto.is_encrypted_db(db_path)

        verifier = None
        if db_is_encrypted and db_crypto.is_sqlcipher_available():

            def verifier(pp: str) -> bool:
                try:
                    import sqlcipher3

                    conn = sqlcipher3.connect(str(db_path))
                    safe = pp.replace("'", "''")
                    conn.execute(f"PRAGMA key='{safe}'")
                    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
                    conn.close()
                    return True
                except Exception:
                    return False

        try:
            pp = passphrase_store.get_passphrase(instance_path, verifier=verifier)
        except passphrase_store.PassphraseUnavailable as e:
            click.echo(f"FAILED: {e}", err=True)
            raise click.Abort() from e

        if pp is None:
            click.echo("FAILED: no passphrase obtained from source.", err=True)
            click.echo("")
            if source == passphrase_store.SOURCE_PROMPT:
                click.echo(
                    "Hint: 'prompt' mode requires a TTY. Run this "
                    "command directly in an interactive shell."
                )
            elif source == passphrase_store.SOURCE_FILE:
                click.echo(f"Hint: 'file' mode expects {instance_path}/backup.key")
            elif source == passphrase_store.SOURCE_ENV:
                click.echo("Hint: 'env' mode expects STOIC_BACKUP_PASSPHRASE")
            raise click.Abort()

        click.echo(f"OK: passphrase obtained ({len(pp)} characters).")
        if db_is_encrypted:
            click.echo("    Verified against the encrypted DB: OK.")
        else:
            click.echo("    DB is currently plain; no verification possible.")
        # Don't print the passphrase itself, ever.
