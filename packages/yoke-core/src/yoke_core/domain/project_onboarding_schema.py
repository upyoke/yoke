"""Native schema declarations for project onboarding checklist runs."""

PROJECT_ONBOARDING_RUNS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS project_onboarding_runs (
    run_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    project_id INTEGER,
    branch TEXT NOT NULL,
    checkout_path TEXT,
    machine_config_path TEXT,
    github_repo TEXT,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
)
"""

PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL = (
    "FOREIGN KEY (run_id) REFERENCES project_onboarding_runs(run_id)"
)

PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS project_onboarding_checklist_rows (
    run_id TEXT NOT NULL,
    row_id TEXT NOT NULL,
    step TEXT NOT NULL,
    title TEXT NOT NULL,
    layer TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    hint TEXT,
    evidence_json TEXT NOT NULL,
    blocker TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, row_id),
    {PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL}
)
"""
