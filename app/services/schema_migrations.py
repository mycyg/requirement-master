"""Small runtime schema patches for the current SQLite-first deployment.

The project currently uses ``Base.metadata.create_all`` instead of Alembic migrations.
These idempotent patches keep existing installs bootable when nullable columns are
added to the requirements table.
"""
from __future__ import annotations

from sqlalchemy import Engine, text


REQUIREMENT_COLUMNS: dict[str, str] = {
    "claimed_by_user_id": "VARCHAR(32)",
    "claimed_by_nickname": "VARCHAR(64)",
    "delivery_doc_ready_at": "DATETIME",
}


def ensure_runtime_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        existing = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(requirements)")).fetchall()
        }
        for name, ddl in REQUIREMENT_COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE requirements ADD COLUMN {name} {ddl}"))

        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_requirements_claimed_by_user_id "
            "ON requirements (claimed_by_user_id)"
        ))
