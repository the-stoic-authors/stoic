"""Stoic ELN — application factory."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask

from stoic_eln.config import Config, DevelopmentConfig, ProductionConfig, TestingConfig
from stoic_eln.extensions import babel, csrf, db, login_manager, migrate

__version__ = "2.0.0a1"

CONFIG_MAP: dict[str, type[Config]] = {
    "debug": DevelopmentConfig,
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def create_app(config_class: type[Config] | None = None) -> Flask:
    """Create and configure a Flask application instance.

    Args:
        config_class: A specific config class, or None to read from FLASK_ENV.
    """
    app = Flask(
        __name__,
        instance_relative_config=False,
        template_folder="templates",
        static_folder="static",
    )

    if config_class is None:
        env = os.environ.get("FLASK_ENV", "debug").lower()
        config_class = CONFIG_MAP.get(env, DevelopmentConfig)

    app.config.from_object(config_class)
    config_class.init_app(app)

    _configure_logging(app)
    _register_extensions(app)
    _register_blueprints(app)
    _register_template_context(app)
    _register_error_handlers(app)
    _register_cli(app)

    return app


def _configure_logging(app: Flask) -> None:
    level = app.config.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    app.logger.info("Stoic ELN v%s starting (env=%s)", __version__, app.config.get("ENV"))


def _register_extensions(app: Flask) -> None:
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


def _select_locale() -> str:
    """Determine which locale to use for the current request.

    Order:
      1. Logged-in user preference (User.locale)
      2. Cookie 'locale' (set by language switcher for anonymous users)
      3. Browser Accept-Language header
      4. Default locale from config
    """
    from flask import current_app, request
    from flask_login import current_user

    if current_user.is_authenticated and current_user.locale:
        return current_user.locale

    cookie_locale = request.cookies.get("locale")
    if cookie_locale in ("it", "en"):
        return cookie_locale

    best = request.accept_languages.best_match(["it", "en"])
    if best:
        return best

    return current_app.config.get("DEFAULT_LOCALE", "it")


def _register_blueprints(app: Flask) -> None:
    from stoic_eln.blueprints.auth import bp as auth_bp
    from stoic_eln.blueprints.inventory import bp as inventory_bp
    from stoic_eln.blueprints.main import bp as main_bp
    from stoic_eln.blueprints.substances import bp as substances_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(substances_bp)
    app.register_blueprint(inventory_bp)


def _register_template_context(app: Flask) -> None:
    """Inject globals into all templates."""

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

        return {
            "app_version": __version__,
            "lab_name": app.config.get("LAB_NAME", "Stoic ELN"),
            "current_theme": theme,
            "get_locale": get_locale,
            "available_locales": [
                ("it", "Italiano"),
                ("en", "English"),
            ],
        }


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
