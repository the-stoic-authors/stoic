"""Tests for the Docker + Caddy deployment manifests (Patch B).

We can't actually run `docker build` or `docker compose up` from
inside the test suite — that needs the Docker daemon and is the
job of CI. What we CAN verify is that the manifests are structurally
sane:

  - Dockerfile parses (multi-stage, COPY/RUN/CMD layout looks right)
  - docker-compose.yml is valid YAML with the expected services,
    volumes, and networks
  - Caddyfile has balanced braces and the right directives
  - .env.example contains the documented variables
  - .dockerignore excludes the dangerous paths

This catches typos and structural regressions before a CI build
job (which costs minutes) discovers them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Dockerfile ─────────────────────────────────────────────────────


def test_dockerfile_exists():
    assert (REPO_ROOT / "Dockerfile").is_file()


def test_dockerfile_is_multistage():
    """Stoic uses a two-stage build (builder + runtime) to keep the
    final image small. Regressions to a single-stage build would
    triple the image size — guard against accidents."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    from_lines = [line for line in content.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) >= 2, (
        f"Dockerfile must be multi-stage; found only {len(from_lines)} FROM lines"
    )
    # Builder should produce a stage named explicitly
    assert any("AS builder" in line for line in from_lines), "first FROM must be named 'builder'"
    assert any("AS runtime" in line for line in from_lines), "final FROM must be named 'runtime'"


def test_dockerfile_runs_as_non_root():
    """The container must not run as root — a hardening baseline.
    The image creates a 'stoic' user and switches with USER."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "USER stoic" in content, "Dockerfile must switch to non-root 'stoic' user"


def test_dockerfile_has_healthcheck():
    """Compose and orchestrators (k8s, swarm) rely on HEALTHCHECK
    to know when Stoic is actually ready, not merely started."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "HEALTHCHECK" in content


def test_dockerfile_uses_tini_or_init():
    """Without tini (or another init), gunicorn is PID 1 and signal
    handling is unreliable — `docker stop` won't shut down cleanly."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "tini" in content, "Dockerfile must use tini as PID 1"


def test_dockerfile_entrypoint_is_gunicorn():
    """The default command should launch gunicorn via the config
    file from Patch A. Anything else would bypass the master-only
    scheduler hook."""
    content = (REPO_ROOT / "Dockerfile").read_text()
    assert "gunicorn" in content
    assert "gunicorn.conf.py" in content
    assert "wsgi:app" in content


# ── docker-compose.yml ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())


def test_compose_has_two_services(compose):
    assert set(compose["services"].keys()) == {"stoic", "caddy"}


def test_compose_caddy_publishes_80_and_443(compose):
    """Caddy is the public face. 80 is needed for the Let's Encrypt
    HTTP-01 challenge; 443 for real traffic."""
    ports = compose["services"]["caddy"].get("ports", [])
    ports_str = " ".join(str(p) for p in ports)
    assert "80:80" in ports_str, "Caddy must publish :80 for ACME challenge"
    assert "443:443" in ports_str, "Caddy must publish :443 for HTTPS"


def test_compose_stoic_does_not_publish_ports(compose):
    """The stoic service is internal only. Publishing its port would
    bypass Caddy and expose Stoic in HTTP — defeats the point of
    putting Caddy in front."""
    stoic = compose["services"]["stoic"]
    assert "ports" not in stoic, "Stoic service must NOT publish ports — it's reached via Caddy"


def test_compose_persistent_volumes_defined(compose):
    """Stoic state must survive container restarts. Three named
    volumes carry the three things that change over time."""
    required = {
        "stoic-instance",
        "stoic-attachments",
        "stoic-backups",
        "caddy-data",
        "caddy-config",
    }
    assert required.issubset(set(compose["volumes"].keys()))


def test_compose_stoic_mounts_all_state_volumes(compose):
    """Each persistent volume must actually be mounted into the
    stoic container, otherwise the data wouldn't be persistent."""
    mounts = compose["services"]["stoic"].get("volumes", [])
    mounts_str = " ".join(mounts)
    assert "stoic-instance" in mounts_str
    assert "stoic-attachments" in mounts_str
    assert "stoic-backups" in mounts_str


def test_compose_caddy_depends_on_healthy_stoic(compose):
    """Caddy should wait for Stoic to actually be ready before
    starting to proxy — otherwise the first user request after
    `docker compose up` hits a 502."""
    caddy = compose["services"]["caddy"]
    depends_on = caddy.get("depends_on", {})
    # condition: service_healthy is the modern compose syntax
    assert "stoic" in depends_on
    if isinstance(depends_on["stoic"], dict):
        assert depends_on["stoic"].get("condition") == "service_healthy"


# ── Caddyfile ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def caddyfile():
    return (REPO_ROOT / "Caddyfile").read_text()


def test_caddyfile_braces_balanced(caddyfile):
    """A typo in the Caddyfile that unbalances braces is the most
    common way to wreck a working compose stack. Pre-check."""
    assert caddyfile.count("{") == caddyfile.count("}")


def test_caddyfile_reverse_proxies_to_stoic_service(caddyfile):
    assert "reverse_proxy stoic:5001" in caddyfile, (
        "Caddy must proxy to the 'stoic' service on port 5001"
    )


def test_caddyfile_uses_stoic_domain_variable(caddyfile):
    """The whole point of the Caddyfile is that ONE env var
    (STOIC_DOMAIN) controls the HTTPS strategy. If we hardcode
    a hostname we lose that ergonomics."""
    assert "{$STOIC_DOMAIN}" in caddyfile


def test_caddyfile_has_security_headers(caddyfile):
    """A handful of headers come essentially for free and are
    expected on any modern HTTPS site."""
    for header in (
        "Strict-Transport-Security",
        "X-Frame-Options",
        "X-Content-Type-Options",
    ):
        assert header in caddyfile, f"missing security header: {header}"


# ── .env.example ───────────────────────────────────────────────────


def test_env_example_documents_required_vars():
    content = (REPO_ROOT / ".env.example").read_text()
    # The required variables must be present (possibly blank) so the
    # user copying to .env knows they exist.
    for var in ("SECRET_KEY", "STOIC_DOMAIN"):
        assert f"{var}=" in content, f".env.example must define {var}"


def test_env_example_does_not_ship_real_secret():
    """A common gotcha: someone fills in a secret in .env.example,
    then commits it. The file must always have a BLANK SECRET_KEY."""
    content = (REPO_ROOT / ".env.example").read_text()
    # Find the SECRET_KEY line and make sure it's empty
    for line in content.splitlines():
        if line.strip().startswith("SECRET_KEY="):
            value = line.split("=", 1)[1].strip()
            assert value == "", f".env.example must ship with SECRET_KEY blank, got: {value!r}"
            return
    pytest.fail("SECRET_KEY line not found in .env.example")


# ── .dockerignore ──────────────────────────────────────────────────


def test_dockerignore_excludes_dangerous_paths():
    """Anything containing secrets, local DB state, or build
    artefacts must be excluded from the Docker build context.
    Failing to ignore .env or instance/ would bake them into the
    image."""
    content = (REPO_ROOT / ".dockerignore").read_text()
    must_exclude = (".env", "instance/", ".venv/", "__pycache__", ".git/")
    for pattern in must_exclude:
        assert pattern in content, f".dockerignore must exclude {pattern!r}"


def test_dockerignore_allows_env_example():
    """While .env is excluded, .env.example needs to be in the build
    context for `cp .env.example .env` to work inside the container
    if a user wants to do that. The `!` re-include pattern handles it."""
    content = (REPO_ROOT / ".dockerignore").read_text()
    assert "!.env.example" in content
