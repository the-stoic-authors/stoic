# Stoic ELN — multi-stage Dockerfile
#
# Two-stage build keeps the runtime image lean: build tools and
# header packages live only in the builder stage, never in the
# final image. Result: roughly 500 MB instead of 1.5 GB+.
#
# Build:
#   docker build -t ghcr.io/the-stoic-authors/stoic:dev .
#
# Run:
#   docker run --rm -p 5001:5001 \
#     -e SECRET_KEY=$(openssl rand -hex 32) \
#     -v stoic-instance:/app/instance \
#     -v stoic-attachments:/app/data/attachments \
#     -v stoic-backups:/app/var/backups \
#     ghcr.io/the-stoic-authors/stoic:dev
#
# In practice you'll run it via docker-compose.yml together with
# Caddy for HTTPS termination — see docs/en/install-docker.md.
#
# ── stage 1: builder ────────────────────────────────────────────

FROM python:3.12-slim-bookworm AS builder

# Build-time system deps. Anything Python that compiles native
# code needs these headers; runtime stage gets only the .so files.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libcairo2-dev \
        libfreetype6-dev \
        libffi-dev \
        pkg-config \
        gettext \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only the dependency manifest first so Docker can cache the
# pip-install layer across rebuilds when the source changes but
# dependencies don't.
COPY pyproject.toml ./

# Install into a venv we can copy verbatim to the runtime stage.
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip wheel setuptools

# Bring the rest of the source in and install Stoic itself.
COPY . /build/

# Install the project (editable not needed in the image — we want
# a real install so files end up under site-packages).
RUN /opt/venv/bin/pip install --no-cache-dir .

# Compile .po → .mo so the translations work at runtime. The .mo
# files are gitignored, so they always need to be (re)built here.
RUN /opt/venv/bin/pybabel compile -d /build/stoic_eln/translations || \
    echo "pybabel compile produced warnings (probably nothing to compile)"

# ── stage 2: runtime ────────────────────────────────────────────

FROM python:3.12-slim-bookworm AS runtime

# Runtime system deps: only the shared libraries Python packages
# need at run time. No -dev packages, no build tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        libfreetype6 \
        # tini: minimal init so signals (SIGTERM from docker stop)
        # propagate to gunicorn cleanly instead of being eaten by
        # PID 1.
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Non-root user for security. Stoic doesn't need root to run.
# Fixed UID/GID so volume permissions remain stable across container
# rebuilds — operators can chown their host directories to 1000:1000.
RUN groupadd --system --gid 1000 stoic && \
    useradd  --system --uid 1000 --gid stoic --create-home --shell /bin/bash stoic

WORKDIR /app

# Pull the prepared venv from the builder. It already contains
# Stoic itself installed as a regular package.
COPY --from=builder /opt/venv /opt/venv

# Bring the source files needed at run time. Most of Stoic lives
# inside the venv via pip install, but wsgi.py and gunicorn.conf.py
# sit at the repo root and are referenced by the gunicorn command
# line, so they have to be present in /app too.
COPY --from=builder /build/wsgi.py /app/wsgi.py
COPY --from=builder /build/gunicorn.conf.py /app/gunicorn.conf.py
COPY --from=builder /build/stoic_eln/translations /opt/venv/lib/python3.12/site-packages/stoic_eln/translations

# Volume mount points. We pre-create them so the entrypoint can
# stat them even before docker-compose mounts named volumes.
RUN mkdir -p /app/instance /app/data/attachments /app/var/backups && \
    chown -R stoic:stoic /app /opt/venv

# The runtime PATH picks up venv binaries first, so `gunicorn`,
# `flask`, etc. resolve from /opt/venv/bin without prefixing.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Default to listening on every interface inside the container.
    # The container network namespace is isolated; "open to LAN" is
    # decided at the docker-compose port-publish layer, not here.
    STOIC_BIND=0.0.0.0:5001 \
    STOIC_WORKERS=2 \
    FLASK_ENV=production

USER stoic

EXPOSE 5001

# Health check: Stoic's login page is always reachable (no auth
# required to GET it) and returns 200 when the app is alive.
# Caddy + compose may add their own checks layered on top.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        r = urllib.request.urlopen('http://127.0.0.1:5001/auth/login', timeout=3); \
        sys.exit(0 if r.status == 200 else 1)" || exit 1

# tini as PID 1 handles signal forwarding to gunicorn. Without it
# `docker stop` waits the full 10-second grace period and then
# SIGKILLs — ungraceful and noisy in logs.
ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
