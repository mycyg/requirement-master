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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS requirement_assignments (
                id VARCHAR(32) PRIMARY KEY,
                requirement_id VARCHAR(32) NOT NULL,
                user_id VARCHAR(32) NOT NULL,
                role VARCHAR(16) NOT NULL,
                assigned_by_user_id VARCHAR(32) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CONSTRAINT uq_requirement_assignment_user UNIQUE (requirement_id, user_id),
                FOREIGN KEY(requirement_id) REFERENCES requirements (id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users (id),
                FOREIGN KEY(assigned_by_user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_requirement_assignments_requirement_id "
            "ON requirement_assignments (requirement_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_requirement_assignments_user_id "
            "ON requirement_assignments (user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_requirement_assignments_assigned_by_user_id "
            "ON requirement_assignments (assigned_by_user_id)"
        ))
        conn.execute(text("""
            INSERT OR IGNORE INTO requirement_assignments (
                id, requirement_id, user_id, role, assigned_by_user_id, created_at, updated_at
            )
            SELECT
                lower(hex(randomblob(16))),
                id,
                claimed_by_user_id,
                'lead',
                submitter_user_id,
                COALESCE(claimed_at, created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            FROM requirements
            WHERE claimed_by_user_id IS NOT NULL
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS project_drive_items (
                id VARCHAR(32) PRIMARY KEY,
                project_id VARCHAR(32) NOT NULL,
                parent_id VARCHAR(32),
                name VARCHAR(256) NOT NULL,
                kind VARCHAR(16) NOT NULL,
                current_version_id VARCHAR(32),
                created_by_user_id VARCHAR(32) NOT NULL,
                updated_by_user_id VARCHAR(32),
                deleted_at DATETIME,
                deleted_by_user_id VARCHAR(32),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY(parent_id) REFERENCES project_drive_items (id) ON DELETE CASCADE,
                FOREIGN KEY(created_by_user_id) REFERENCES users (id),
                FOREIGN KEY(updated_by_user_id) REFERENCES users (id),
                FOREIGN KEY(deleted_by_user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_items_project_id "
            "ON project_drive_items (project_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_items_parent_id "
            "ON project_drive_items (parent_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_items_current_version_id "
            "ON project_drive_items (current_version_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_items_deleted_at "
            "ON project_drive_items (deleted_at)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_items_created_by_user_id "
            "ON project_drive_items (created_by_user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_items_updated_by_user_id "
            "ON project_drive_items (updated_by_user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_items_deleted_by_user_id "
            "ON project_drive_items (deleted_by_user_id)"
        ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS project_drive_versions (
                id VARCHAR(32) PRIMARY KEY,
                item_id VARCHAR(32) NOT NULL,
                version_no INTEGER NOT NULL,
                filename VARCHAR(256) NOT NULL,
                mime VARCHAR(128),
                size_bytes BIGINT NOT NULL,
                storage_path VARCHAR(512) NOT NULL,
                sha256 VARCHAR(64),
                parsed_text TEXT,
                parsed_text_path VARCHAR(512),
                created_by_user_id VARCHAR(32) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CONSTRAINT uq_project_drive_version_no UNIQUE (item_id, version_no),
                FOREIGN KEY(item_id) REFERENCES project_drive_items (id) ON DELETE CASCADE,
                FOREIGN KEY(created_by_user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_versions_item_id "
            "ON project_drive_versions (item_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_versions_created_by_user_id "
            "ON project_drive_versions (created_by_user_id)"
        ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS project_drive_operations (
                id VARCHAR(32) PRIMARY KEY,
                project_id VARCHAR(32) NOT NULL,
                actor_user_id VARCHAR(32) NOT NULL,
                op_type VARCHAR(32) NOT NULL,
                payload_json TEXT NOT NULL,
                undone_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY(actor_user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_operations_project_id "
            "ON project_drive_operations (project_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_operations_actor_user_id "
            "ON project_drive_operations (actor_user_id)"
        ))
