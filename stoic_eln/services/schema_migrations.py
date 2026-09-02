"""Stoic ELN — additive schema migrations that ship inside the package.

``flask ensure-schema`` runs ``db.create_all()``, which creates missing
*tables* but never adds a *column* to a table that already exists. So
every patch that adds a column needs its own migration step.

Historically those lived in ``scripts/``, which is not copied into the
Docker image — on stoichub they had to be retyped as
``docker compose exec stoic python -c "..."`` one-liners. Putting the
logic here instead means the matching ``flask`` command is available
wherever the package is installed, container included, and the logic is
covered by tests like any other service.

Every migration in this module must be idempotent: running it twice is a
no-op, and running it against a fresh database created by
``db.create_all()`` reports nothing to do.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


# ── v1.4.4: incremental deduction bookkeeping on step components ────
#
# SQLite adds a nullable column in place (no table rebuild), and none of
# these carries a FOREIGN KEY — ``deducted_lot_id`` is a plain INTEGER
# precisely so this stays a simple ADD COLUMN.
STEP_DEDUCTION_COLUMNS: dict[str, str] = {
    "deducted_lot_id": "INTEGER",
    "deducted_mass_g": "FLOAT",
    "deducted_volume_mL": "FLOAT",
}


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


# ── v1.5.0: solvent recovery ────────────────────────────────────────
#
# Same reasoning as above: nullable columns and plain INTEGERs, no FK,
# so SQLite adds them in place. The two NOT NULL flags get a DEFAULT so
# existing rows are backfilled by the ALTER itself — an existing lot is
# not recovered, and has been round-tripped zero times.
RECOVERY_COLUMNS: dict[str, dict[str, str]] = {
    "inventory_item": {
        "is_recovered": "BOOLEAN NOT NULL DEFAULT 0",
        "recovery_use_count": "INTEGER NOT NULL DEFAULT 0",
        "recovered_at": "DATETIME",
        "recovered_from_step_id": "INTEGER",
        "origin_reaction_id": "INTEGER",
    },
    "mixture": {
        "is_recovered": "BOOLEAN NOT NULL DEFAULT 0",
        "recovery_signature": "VARCHAR(200)",
    },
}


def ensure_recovery_columns(engine: Engine) -> list[str]:
    """Add the v1.5.0 solvent-recovery columns if missing.

    Idempotent, like every migration in this module.
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    actions: list[str] = []

    for table, columns in RECOVERY_COLUMNS.items():
        if table not in tables:
            actions.append(f"table {table} absent — db.create_all() will create it complete")
            continue
        for column, sql_type in columns.items():
            if _has_column(insp, table, column):
                actions.append(f"{table}.{column} already present — skip")
                continue
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
            actions.append(f"{table}.{column} added ({sql_type})")

    return actions


def ensure_step_deduction_columns(engine: Engine) -> list[str]:
    """Add the ``run_step_component.deducted_*`` columns if missing.

    Returns a human-readable log of what was done, one line per column,
    for the CLI command to echo.
    """
    table = "run_step_component"
    insp = inspect(engine)
    actions: list[str] = []

    if table not in insp.get_table_names():
        return [f"table {table} absent — db.create_all() will create it complete"]

    for column, sql_type in STEP_DEDUCTION_COLUMNS.items():
        if _has_column(insp, table, column):
            actions.append(f"{table}.{column} already present — skip")
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
        actions.append(f"{table}.{column} added ({sql_type}, NULL)")

    return actions
