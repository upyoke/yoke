"""Focused deployment pipeline database fixture schema."""

DEPLOYMENT_PIPELINE_SCHEMA = """
    CREATE TABLE items (
        id INTEGER PRIMARY KEY,
        title TEXT,
        status TEXT DEFAULT 'implemented',
        project_id INTEGER DEFAULT 1,
        project_sequence INTEGER NOT NULL,
        deployment_flow TEXT,
        deploy_stage TEXT,
        deployed_to TEXT,
        github_issue TEXT,
        frozen INTEGER DEFAULT 0
    );
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        slug TEXT UNIQUE,
        name TEXT,
        github_repo TEXT,
        default_branch TEXT DEFAULT 'main',
        public_item_prefix TEXT DEFAULT 'YOK'
    );
    CREATE TABLE sites (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL,
        name TEXT NOT NULL
    );
    CREATE TABLE environments (
        id INTEGER PRIMARY KEY,
        site INTEGER NOT NULL,
        project_id INTEGER NOT NULL,
        name TEXT NOT NULL
    );
    CREATE TABLE deployment_flows (
        id TEXT PRIMARY KEY,
        project_id INTEGER,
        name TEXT,
        stages TEXT,
        target_tier TEXT,
        target_environment_id INTEGER
    );
    CREATE TABLE deployment_runs (
        id TEXT PRIMARY KEY,
        project_id INTEGER,
        flow TEXT,
        target_tier TEXT,
        target_environment_id INTEGER,
        release_lineage TEXT,
        status TEXT DEFAULT 'created',
        current_stage TEXT,
        created_at TIMESTAMPTZ,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        created_by TEXT DEFAULT 'operator'
    );
    CREATE TABLE deployment_run_items (
        run_id TEXT,
        item_id INTEGER,
        added_at TIMESTAMPTZ,
        PRIMARY KEY (run_id, item_id)
    );
    CREATE TABLE deployment_run_qa (
        id INTEGER PRIMARY KEY,
        run_id TEXT,
        check_name TEXT,
        source TEXT DEFAULT 'flow_default',
        blocking INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending',
        updated_at TIMESTAMPTZ,
        UNIQUE(run_id, check_name)
    );
    CREATE TABLE qa_requirements (
        id INTEGER PRIMARY KEY,
        item_id INTEGER,
        deployment_run_id TEXT,
        qa_kind TEXT,
        qa_phase TEXT,
        blocking_mode TEXT DEFAULT 'blocking',
        requirement_source TEXT,
        success_policy TEXT
    );
    CREATE TABLE qa_runs (
        id INTEGER PRIMARY KEY,
        qa_requirement_id INTEGER,
        step_runner_type TEXT,
        qa_kind TEXT,
        verdict TEXT,
        raw_result TEXT,
        completed_at TIMESTAMPTZ,
        duration_ms INTEGER,
        created_at TIMESTAMPTZ,
        started_at TIMESTAMPTZ
    );
    CREATE TABLE qa_plan_review_verdicts (
        requirement_id INTEGER,
        capture_run_id INTEGER,
        review_run_id INTEGER
    );
    CREATE TABLE qa_artifacts (
        id INTEGER PRIMARY KEY,
        qa_run_id INTEGER,
        artifact_type TEXT,
        content_type TEXT,
        metadata TEXT
    );
    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        event_name TEXT,
        event_type TEXT,
        source_type TEXT,
        created_at TIMESTAMPTZ,
        client_timing_id TEXT,
        envelope TEXT
    );
"""
