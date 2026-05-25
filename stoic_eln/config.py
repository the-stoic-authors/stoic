"""Stoic ELN — configuration classes."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

# Load .env file from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    """Base configuration."""

    ENV = "base"
    DEBUG = False
    TESTING = False

    # Security
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7 days

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///stoic_eln.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }

    # i18n
    BABEL_DEFAULT_LOCALE = os.environ.get("DEFAULT_LOCALE", "it")
    BABEL_DEFAULT_TIMEZONE = "UTC"
    BABEL_TRANSLATION_DIRECTORIES = "translations"
    DEFAULT_LOCALE = BABEL_DEFAULT_LOCALE

    # UI
    LAB_NAME = os.environ.get("LAB_NAME", "Mio Laboratorio")
    DEFAULT_THEME = os.environ.get("DEFAULT_THEME", "system")

    # Attachments (Settimana 6 patch 10)
    # Storage directory is interpreted relative to PROJECT_ROOT when not absolute.
    ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "data/attachments")
    # Hard cap on individual upload size. Werkzeug enforces this via
    # MAX_CONTENT_LENGTH; the service layer applies the same number for a
    # nice flash message instead of a raw 413.
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB

    # Logging
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    @staticmethod
    def init_app(app: Flask) -> None:
        """Hook for subclasses to perform additional setup."""
        pass


class DevelopmentConfig(Config):
    """Development configuration with debug enabled."""

    ENV = "development"
    DEBUG = True
    SESSION_COOKIE_SECURE = False  # Allow HTTP in dev


class TestingConfig(Config):
    """Configuration used by pytest."""

    ENV = "testing"
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-key-not-secret"


class ProductionConfig(Config):
    """Production configuration with security hardening."""

    ENV = "production"
    DEBUG = False
    SESSION_COOKIE_SECURE = True

    @staticmethod
    def init_app(app: Flask) -> None:
        # Verify mandatory env vars
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError(
                "SECRET_KEY must be set in production. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
