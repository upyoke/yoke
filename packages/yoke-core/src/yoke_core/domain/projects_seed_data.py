"""Project-registry seed vocabulary.

Seeds the generic capability-template vocabulary and initializes the
Project Structure aggregate tables. A fresh universe seeds NO project
rows: the ``projects`` table starts empty and projects enter through
onboarding (``yoke project install`` / ``projects_upsert``). Operator
project registry data (identities, sites, environments, capability
settings) lives in the operator's private ops repo and is applied by
operator tooling, never by this engine.

Connection ownership: callers (notably ``cmd_init``) own the DB connection
and the surrounding transaction. Helpers in this module run
``conn.execute`` and ``conn.commit`` as needed for batched inserts but do
not open or close the connection.

Owner: ``yoke_core.domain.projects_restart``.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.github_actions_runner_fleet_capability import (
    CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
)


def _placeholder(conn) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Capability templates
# ---------------------------------------------------------------------------

# Tuple shape: (id, name, description, required_config_json, requires_json).
CAPABILITY_TEMPLATES: list[tuple[str, str, str, str, str]] = [
    (
        "ssh", "SSH Access",
        "SSH access to a remote server",
        '[{"key":"user","description":"SSH username","secret":false},'
        '{"key":"host","description":"Server hostname or IP","secret":false},'
        '{"key":"key_path","description":"Path to SSH private key","secret":false}]',
        "[]",
    ),
    (
        "docker", "Docker",
        "Docker daemon accessible for container operations",
        '[{"key":"host","description":"Docker host (default: local)","secret":false}]',
        "[]",
    ),
    (
        "container-registry", "Container Registry",
        "Project container-image registry (ECR). One repository per project; "
        "image tags are git SHAs; deploy stages pull from here. "
        "Requires aws-admin.",
        '[{"key":"repository","description":"Registry repository name (e.g. <project>-core)","secret":false}]',
        '["aws-admin"]',
    ),
    (
        "ephemeral-env", "Ephemeral Environment",
        "Ability to spin up and tear down per-branch environments",
        '[{"key":"web_base_port","description":"Base port for this project web-preview ephemeral envs","secret":false},'
        '{"key":"api_base_port","description":"Base port for this project API ephemeral envs","secret":false},'
        '{"key":"compose_file","description":"docker-compose file for ephemeral env","secret":false},'
        '{"key":"env_file","description":"Path to .env file for ephemeral env secrets","secret":false},'
        '{"key":"startup_timeout_s","description":"Seconds to wait for health check after start","secret":false}]',
        '["docker"]',
    ),
    (
        "aws-admin", "AWS Admin",
        "AWS credentials with broad admin access. Parent for all AWS capabilities.",
        '[{"key":"access_key_id","description":"AWS Access Key ID","secret":true},'
        '{"key":"secret_access_key","description":"AWS Secret Access Key","secret":true},'
        '{"key":"region","description":"Default AWS region","secret":false}]',
        "[]",
    ),
    (
        "aws-route53", "AWS Route53",
        "DNS management via Route53. Requires aws-admin.",
        '[{"key":"hosted_zone_id","description":"Route53 Hosted Zone ID","secret":false}]',
        '["aws-admin"]',
    ),
    (
        "github", "GitHub Integration",
        "GitHub App repo binding for issue sync, PRs, Actions, and API access",
        '[{"key":"repo_owner","description":"GitHub repo owner","secret":false},'
        '{"key":"repo_name","description":"GitHub repo name","secret":false},'
        '{"key":"installation_id","description":"GitHub App installation id","secret":false},'
        '{"key":"repository_id","description":"GitHub repository id","secret":false}]',
        "[]",
    ),
    (
        RUNNER_FLEET_CAPABILITY_TYPE,
        "GitHub Actions Runner Fleet",
        "Dedicated EC2-backed self-hosted GitHub Actions runner capacity. "
        "Requires github and aws-admin.",
        '[{"key":"repo","description":"GitHub repo slug owner/name","secret":false},'
        '{"key":"runner_labels","description":"Required runs-on labels","secret":false},'
        '{"key":"variable_name","description":"Actions variable holding the runs-on array","secret":false},'
        '{"key":"desired_runner_count","description":"Normal parallel runner count","secret":false},'
        '{"key":"max_runner_count","description":"Maximum parallel runner count","secret":false},'
        '{"key":"instance","description":"EC2 instance sizing settings","secret":false},'
        '{"key":"lifecycle","description":"Start and idle-shutdown settings","secret":false}]',
        '["github","aws-admin"]',
    ),
    (
        "health-endpoint", "Health Endpoint",
        "HTTP health check URL for production monitoring",
        '[{"key":"url","description":"Health check URL","secret":false}]',
        "[]",
    ),
    (
        "vps-ssh", "VPS SSH Access",
        "SSH connectivity to a VPS for reachability checks",
        '[{"key":"host","description":"SSH host (user@host or hostname)","secret":false}]',
        '["ssh"]',
    ),
    (
        "browser-qa", "Browser QA",
        "Browser automation and scenario-based QA testing. "
        "Enables browser-testable classification and automatic seeding "
        "of browser smoke/e2e requirements.",
        '[{"key":"enabled","description":"Enable browser QA seeding for this project","secret":false},'
        '{"key":"default_qa_kinds","description":"Default QA kinds to seed (e2e, smoke, visual_regression)","secret":false},'
        '{"key":"playwright_config","description":"Path to playwright.config.ts (optional)","secret":false}]',
        "[]",
    ),
    (
        "db-backup-s3", "S3 DB Backup",
        "Optional S3-backed backup for yoke.db. Uploads local backups to S3 "
        "for off-machine durability. Requires aws-admin. "
        "Does NOT auto-enable from aws-admin presence alone.",
        '[{"key":"bucket","description":"S3 bucket name","secret":false},'
        '{"key":"prefix","description":"S3 key prefix (e.g. yoke/backups/)","secret":false},'
        '{"key":"region","description":"AWS region (optional if inherited from aws-admin)","secret":false},'
        '{"key":"storage_class","description":"S3 storage class (STANDARD, STANDARD_IA, etc.)","secret":false},'
        '{"key":"required_upload","description":"If true, upload failure blocks destructive ops (default: false)","secret":false},'
        '{"key":"retention_count_remote","description":"Max remote backups to keep (oldest pruned after upload)","secret":false}]',
        '["aws-admin"]',
    ),
]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def seed_capability_templates(conn) -> None:
    """Seed ``capability_templates`` rows from :data:`CAPABILITY_TEMPLATES`."""
    p = _placeholder(conn)
    for tmpl_id, tmpl_name, tmpl_desc, tmpl_config, tmpl_requires in CAPABILITY_TEMPLATES:
        conn.execute(
            "INSERT INTO capability_templates "
            "(id, name, description, required_config, requires, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
            "ON CONFLICT(id) DO NOTHING",
            (tmpl_id, tmpl_name, tmpl_desc, tmpl_config, tmpl_requires,
             iso8601_now()),
        )
    conn.commit()


def seed_project_structure_tables(conn, db_path: Optional[str]) -> None:
    """Create the Project Structure aggregate tables (no per-project data)."""
    from yoke_core.domain import project_structure as ps

    ps.cmd_init(db_path=db_path)
    conn.commit()


def seed_all(conn, db_path: Optional[str]) -> None:
    """Run every seed pass against ``conn`` in the canonical order.

    Callers (e.g. ``projects_restart.cmd_init``) own the surrounding
    transaction; per-pass commits batch the idempotent seed work. Seeds
    only project-agnostic vocabulary: capability templates and the
    Project Structure tables. Existing projects (none on a fresh
    universe) get their default policy capabilities backfilled.
    """
    from yoke_core.domain.projects_seed_ci_workflow import (
        seed_ci_workflow_capability_template,
    )
    from yoke_core.domain.project_policy_capabilities import (
        ensure_default_policy_capabilities,
    )

    seed_capability_templates(conn)
    seed_ci_workflow_capability_template(conn)
    ensure_default_policy_capabilities(conn)
    conn.commit()
    seed_project_structure_tables(conn, db_path)
