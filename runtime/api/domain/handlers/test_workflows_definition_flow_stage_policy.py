"""The release policy a flow's stages declare, as the registry read serves it.

Verdict authority, notification recipients, QA scope and the preview target
are the terms every run freezes when it references the flow. A projection
that served stage names alone hid all of them from every reader who was not
holding the definition file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.workflows_definition_read import get_workflows_definition


PREVIEW_STAGES = [
    {
        "name": "preview-deploy",
        "step_runner": "ephemeral-deploy",
        "stage_kind": "execution",
        "target": {"kind": "run_preview", "capability": "ephemeral-env"},
    },
    {
        "name": "item-qa",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "item",
        "target": {"kind": "run_preview", "source_stage": "preview-deploy"},
        "cases": {"plan_id": 7, "case_keys": ["preview-url-compare"]},
        "verdict": {
            "mode": "required_human",
            "reviewers": {"roles": ["owner"], "mode": "any"},
        },
        "notification": {"enabled": True, "recipients": {"item_owners": True}},
    },
]


def _insert_flow(conn, project_slug: str, flow_id: str, stages: list) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    project_id = int(
        dict(
            conn.execute(
                "SELECT id FROM projects WHERE slug = %s", (project_slug,)
            ).fetchone()
        )["id"]
    )
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, on_failure, created_at, "
        "definition_schema_version) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (flow_id, project_id, flow_id, dumps_compact(stages), "halt", now, 2),
    )
    conn.commit()


class TestFlowStagePolicy:
    def test_a_qa_stage_carries_its_scope_verdict_and_recipients(self, test_db):
        _insert_flow(test_db, "yoke", "preview-then-prod", PREVIEW_STAGES)

        stages = get_workflows_definition(project="yoke")["flows"][0]["stages"]
        assert [stage["name"] for stage in stages] == ["preview-deploy", "item-qa"]
        assert stages[1]["stage_kind"] == "qa"
        assert stages[1]["scope"] == "item"
        assert stages[1]["cases"] == {
            "plan_id": 7,
            "case_keys": ["preview-url-compare"],
        }
        # Who rules on the stage and who is merely told stay separate, because
        # a recipient list is not decision authority.
        assert stages[1]["verdict"] == {
            "mode": "required_human",
            "reviewers": {"roles": ["owner"], "mode": "any"},
        }
        assert stages[1]["notification"] == {
            "enabled": True,
            "recipients": {"item_owners": True},
        }

    def test_a_preview_target_names_the_stage_that_built_it(self, test_db):
        # An ephemeral substrate has no name a reader could look up, so the
        # QA stage points at the execution stage that produced it.
        _insert_flow(test_db, "yoke", "preview-target", PREVIEW_STAGES)

        stages = get_workflows_definition(project="yoke")["flows"][0]["stages"]
        assert stages[0]["target"] == {
            "kind": "run_preview",
            "capability": "ephemeral-env",
        }
        assert stages[1]["target"] == {
            "kind": "run_preview",
            "source_stage": "preview-deploy",
        }

    def test_a_legacy_stage_carries_no_policy_it_never_declared(self, test_db):
        _insert_flow(
            test_db,
            "yoke",
            "legacy-shape",
            [{"name": "stage-deploy", "step_runner": "auto"}],
        )

        stages = get_workflows_definition(project="yoke")["flows"][0]["stages"]
        assert stages == [{"name": "stage-deploy", "step_runner": "auto"}]

    def test_a_flow_carries_its_description_lineage_and_runner_parameters(
        self, test_db
    ):
        # The Flows page says what runs each stage ("GitHub Actions ·
        # release.yml") and which definition a flow replaces, so the read
        # serves the workflow file, the description and the lineage link.
        _insert_flow(
            test_db,
            "yoke",
            "ship-it",
            [
                {
                    "name": "ship",
                    "step_runner": "github-actions-workflow",
                    "workflow": "release.yml",
                    "inputs": {"target_environment": "prod"},
                },
                {"name": "warm", "step_runner": "warm-up", "connection_env": "prod"},
            ],
        )
        test_db.execute(
            "UPDATE deployment_flows SET description = %s, supersedes_flow_id = %s "
            "WHERE id = %s",
            ("Ship to production.", None, "ship-it"),
        )
        test_db.commit()

        flow = get_workflows_definition(project="yoke")["flows"][0]
        assert flow["description"] == "Ship to production."
        assert flow["supersedes_flow_id"] is None
        # Runner parameters a reader needs are served; dispatch inputs are not.
        assert flow["stages"] == [
            {
                "name": "ship",
                "step_runner": "github-actions-workflow",
                "workflow": "release.yml",
            },
            {"name": "warm", "step_runner": "warm-up", "connection_env": "prod"},
        ]

    def test_people_a_stage_names_are_served_by_name(self, test_db):
        actor = test_db.execute(
            "SELECT id, name FROM actors WHERE name <> '' ORDER BY id LIMIT 1"
        ).fetchone()
        assert actor is not None
        actor = dict(actor)
        _insert_flow(
            test_db,
            "yoke",
            "approved-release",
            [
                {
                    "name": "approve",
                    "step_runner": "human-approval",
                    "approvals": {"actors": [actor["id"]], "mode": "any"},
                }
            ],
        )

        result = get_workflows_definition(project="yoke")
        assert result["flow_actor_names"] == {str(actor["id"]): actor["name"]}
