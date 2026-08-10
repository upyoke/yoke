"""CI workflow and merge-queue capability template seeds.

Owner: ``yoke_core.domain.projects_seed_data`` calls these helpers as part
of the ``seed_all`` pipeline.

Capability shapes:

* ``type = "ci_workflow_file"`` — single per-project row whose ``settings``
  JSON carries ``{"workflow_file": "<filename>"}``.
* ``type = "merge_queue"`` — presence-only declaration that the project's
  item branches land through the GitHub merge queue (PR + merge-when-ready;
  the queue runs the CI workflow's ``merge_group`` gate on the combined
  head). Projects without the row keep the standalone merge engine.

Only the TEMPLATES are seeded here; per-project rows are operator/onboarding
data written through the capability settings surfaces.

The Doctor HC ``HC-projects-ci-workflow-configured``
(:mod:`yoke_core.engines.doctor_hc_projects_ci`) WARNs when a project
row has ``github_repo`` set but no row in this capability table — that is
the operator nudge to declare the workflow filename.
"""

from __future__ import annotations

import json

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.db_helpers import iso8601_now


CI_WORKFLOW_CAPABILITY_TYPE = "ci_workflow_file"


def _placeholder(conn) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


CI_WORKFLOW_CAPABILITY_TEMPLATE: tuple[str, str, str, str, str] = (
    CI_WORKFLOW_CAPABILITY_TYPE,
    "CI Workflow File",
    (
        "GitHub Actions workflow filename for this project's pre-merge "
        "CI gate. Used by the pre-merge CI check in usher and by the "
        "branch-protection doctor HC. Filename only (e.g. ci.yml), "
        "not a path."
    ),
    json.dumps(
        [
            {
                "key": "workflow_file",
                "description": (
                    "Filename under .github/workflows/ for this project's "
                    "required-status-check workflow (e.g. yoke-ci.yml)."
                ),
                "secret": False,
            }
        ]
    ),
    "[]",
)


MERGE_QUEUE_CAPABILITY_TYPE = "merge_queue"


MERGE_QUEUE_CAPABILITY_TEMPLATE: tuple[str, str, str, str, str] = (
    MERGE_QUEUE_CAPABILITY_TYPE,
    "Merge Queue",
    (
        "Item branches for this project land through the GitHub merge "
        "queue: the merge boundary opens/reuses a PR, enters it with "
        "merge-when-ready after admission control, and the queue runs "
        "one merge_group CI gate per train of queued PRs. Requires the "
        "CI workflow to carry a merge_group trigger and a branch ruleset "
        "requiring that check. Absent this capability, the standalone "
        "merge engine remains the merge boundary."
    ),
    "[]",
    json.dumps([CI_WORKFLOW_CAPABILITY_TYPE, "github"]),
)


def _insert_template(conn, template: tuple[str, str, str, str, str]) -> None:
    p = _placeholder(conn)
    tmpl_id, tmpl_name, tmpl_desc, tmpl_config, tmpl_requires = template
    conn.execute(
        "INSERT INTO capability_templates "
        "(id, name, description, required_config, requires, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT(id) DO NOTHING",
        (tmpl_id, tmpl_name, tmpl_desc, tmpl_config, tmpl_requires,
         iso8601_now()),
    )
    conn.commit()


def seed_ci_workflow_capability_template(conn) -> None:
    """Insert the CI workflow capability template row (idempotent)."""
    _insert_template(conn, CI_WORKFLOW_CAPABILITY_TEMPLATE)


def seed_merge_queue_capability_template(conn) -> None:
    """Insert the merge-queue capability template row (idempotent)."""
    _insert_template(conn, MERGE_QUEUE_CAPABILITY_TEMPLATE)
