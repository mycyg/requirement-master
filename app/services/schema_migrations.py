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
    "start_at": "DATETIME",
    "due_at": "DATETIME",
    "source_meeting_id": "VARCHAR(32)",
    "source_requirement_id": "VARCHAR(32)",
}

USER_COLUMNS: dict[str, str] = {
    "availability_status": "VARCHAR(16) DEFAULT 'free' NOT NULL",
    "availability_text": "VARCHAR(128)",
    "availability_updated_at": "DATETIME",
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

        user_existing = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        for name, ddl in USER_COLUMNS.items():
            if name not in user_existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
        conn.execute(text("UPDATE users SET availability_status = 'free' WHERE availability_status IS NULL"))

        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_requirements_claimed_by_user_id "
            "ON requirements (claimed_by_user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_requirements_source_meeting_id "
            "ON requirements (source_meeting_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_requirements_source_requirement_id "
            "ON requirements (source_requirement_id)"
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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS project_drive_comments (
                id VARCHAR(32) PRIMARY KEY,
                project_id VARCHAR(32) NOT NULL,
                folder_id VARCHAR(32),
                author_user_id VARCHAR(32) NOT NULL,
                author_nickname VARCHAR(64) NOT NULL,
                body TEXT NOT NULL,
                status VARCHAR(32) DEFAULT 'pending_llm' NOT NULL,
                llm_kind VARCHAR(32),
                llm_reason TEXT,
                draft_requirement_id VARCHAR(32),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY(folder_id) REFERENCES project_drive_items (id) ON DELETE CASCADE,
                FOREIGN KEY(author_user_id) REFERENCES users (id),
                FOREIGN KEY(draft_requirement_id) REFERENCES requirements (id)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_comments_project_id "
            "ON project_drive_comments (project_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_comments_folder_id "
            "ON project_drive_comments (folder_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_comments_author_user_id "
            "ON project_drive_comments (author_user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_comments_status "
            "ON project_drive_comments (status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_project_drive_comments_draft_requirement_id "
            "ON project_drive_comments (draft_requirement_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_events (
                id VARCHAR(32) PRIMARY KEY,
                project_id VARCHAR(32),
                requirement_id VARCHAR(32),
                created_by_user_id VARCHAR(32) NOT NULL,
                title VARCHAR(256) NOT NULL,
                description TEXT,
                event_type VARCHAR(32) DEFAULT 'custom' NOT NULL,
                start_at DATETIME,
                end_at DATETIME NOT NULL,
                participant_user_ids_json TEXT DEFAULT '[]' NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY(requirement_id) REFERENCES requirements (id) ON DELETE CASCADE,
                FOREIGN KEY(created_by_user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_schedule_events_project_id "
            "ON schedule_events (project_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_schedule_events_requirement_id "
            "ON schedule_events (requirement_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_schedule_events_created_by_user_id "
            "ON schedule_events (created_by_user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_schedule_events_event_type "
            "ON schedule_events (event_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_schedule_events_end_at "
            "ON schedule_events (end_at)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS background_jobs (
                id VARCHAR(32) PRIMARY KEY,
                kind VARCHAR(64) NOT NULL,
                status VARCHAR(16) DEFAULT 'queued' NOT NULL,
                progress_percent INTEGER DEFAULT 0 NOT NULL,
                message TEXT,
                result_ref VARCHAR(128),
                error TEXT,
                created_by_user_id VARCHAR(32) NOT NULL,
                started_at DATETIME,
                finished_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(created_by_user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_background_jobs_kind ON background_jobs (kind)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_background_jobs_status ON background_jobs (status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_background_jobs_result_ref ON background_jobs (result_ref)"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_background_jobs_created_by_user_id "
            "ON background_jobs (created_by_user_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS meeting_records (
                id VARCHAR(32) PRIMARY KEY,
                project_id VARCHAR(32) NOT NULL,
                requirement_id VARCHAR(32),
                uploaded_by_user_id VARCHAR(32) NOT NULL,
                title VARCHAR(256) NOT NULL,
                audio_filename VARCHAR(256) NOT NULL,
                audio_mime VARCHAR(128),
                audio_size_bytes BIGINT NOT NULL,
                audio_path VARCHAR(512) NOT NULL,
                transcript_text TEXT,
                minutes_md TEXT,
                status VARCHAR(32) DEFAULT 'processing' NOT NULL,
                job_id VARCHAR(32),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY(requirement_id) REFERENCES requirements (id) ON DELETE SET NULL,
                FOREIGN KEY(uploaded_by_user_id) REFERENCES users (id),
                FOREIGN KEY(job_id) REFERENCES background_jobs (id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_records_project_id ON meeting_records (project_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_records_requirement_id ON meeting_records (requirement_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_records_uploaded_by_user_id ON meeting_records (uploaded_by_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_records_status ON meeting_records (status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_records_job_id ON meeting_records (job_id)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS meeting_insights (
                id VARCHAR(32) PRIMARY KEY,
                meeting_id VARCHAR(32) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                title VARCHAR(256) NOT NULL,
                description TEXT NOT NULL,
                target_requirement_id VARCHAR(32),
                confidence_reason TEXT,
                status VARCHAR(32) DEFAULT 'pending' NOT NULL,
                created_requirement_id VARCHAR(32),
                confirmed_by_user_id VARCHAR(32),
                confirmed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(meeting_id) REFERENCES meeting_records (id) ON DELETE CASCADE,
                FOREIGN KEY(target_requirement_id) REFERENCES requirements (id),
                FOREIGN KEY(created_requirement_id) REFERENCES requirements (id),
                FOREIGN KEY(confirmed_by_user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_insights_meeting_id ON meeting_insights (meeting_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_insights_kind ON meeting_insights (kind)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_insights_status ON meeting_insights (status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_insights_target_requirement_id ON meeting_insights (target_requirement_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meeting_insights_created_requirement_id ON meeting_insights (created_requirement_id)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS requirement_workspaces (
                id VARCHAR(32) PRIMARY KEY,
                requirement_id VARCHAR(32) NOT NULL,
                user_id VARCHAR(32) NOT NULL,
                phase VARCHAR(64) DEFAULT '未开始' NOT NULL,
                progress_percent INTEGER DEFAULT 0 NOT NULL,
                status_note TEXT,
                blocked_reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                CONSTRAINT uq_requirement_workspace_user UNIQUE (requirement_id, user_id),
                FOREIGN KEY(requirement_id) REFERENCES requirements (id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirement_workspaces_requirement_id ON requirement_workspaces (requirement_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirement_workspaces_user_id ON requirement_workspaces (user_id)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS requirement_workspace_items (
                id VARCHAR(32) PRIMARY KEY,
                workspace_id VARCHAR(32) NOT NULL,
                title VARCHAR(256) NOT NULL,
                status VARCHAR(16) DEFAULT 'todo' NOT NULL,
                sort_order INTEGER DEFAULT 0 NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES requirement_workspaces (id) ON DELETE CASCADE
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirement_workspace_items_workspace_id ON requirement_workspace_items (workspace_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirement_workspace_items_status ON requirement_workspace_items (status)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS requirement_progress_updates (
                id VARCHAR(32) PRIMARY KEY,
                requirement_id VARCHAR(32) NOT NULL,
                workspace_id VARCHAR(32),
                actor_user_id VARCHAR(32) NOT NULL,
                actor_nickname VARCHAR(64) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                body TEXT NOT NULL,
                phase VARCHAR(64),
                progress_percent INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(requirement_id) REFERENCES requirements (id) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id) REFERENCES requirement_workspaces (id) ON DELETE CASCADE,
                FOREIGN KEY(actor_user_id) REFERENCES users (id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirement_progress_updates_requirement_id ON requirement_progress_updates (requirement_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirement_progress_updates_workspace_id ON requirement_progress_updates (workspace_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirement_progress_updates_actor_user_id ON requirement_progress_updates (actor_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirement_progress_updates_kind ON requirement_progress_updates (kind)"))
