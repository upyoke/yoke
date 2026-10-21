"""Dash and Blitz skill distribution invariants."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from yoke_cli.commands.adapters import items_create
from yoke_core.domain.builtin_direct_workflow_definitions import (
    BLITZ_WORKFLOW_DEFINITION,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers.direct_workflow_execution import (
    REGISTRATIONS as DIRECT_WORKFLOW_REGISTRATIONS,
)
from yoke_core.domain.yoke_function_registry import lookup
from runtime.api.skill_doc_regressions_test_helpers import _read_skill_corpus


ROOT = Path(__file__).parents[2]
_TREE = "packages/yoke-core/src/yoke_core/install_bundle_tree"
BUNDLE = ROOT / _TREE / ".agents/skills/yoke"
CANONICAL = ROOT / ".agents/skills/yoke"


def _skill_corpus(skill: str) -> str:
    return _read_skill_corpus(CANONICAL / skill)


def test_idea_to_blitz_route_dispatches_the_typed_create_payload(monkeypatch):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(items_create, "dispatch_create", _dispatch)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Roll out the linked document; done when it lands."),
    )

    assert (
        items_create.items_create(
            [
                "--title",
                "Reconcile the document-led rollout",
                "--workflow",
                "blitz",
                "--stdin",
                "--entry-surface",
                "harness_skill",
                "--project",
                "yoke",
                "--execution-instructions-considered",
            ]
        )
        == 0
    )
    assert captured["target"].kind == "global"
    assert captured["target"].project_id == "yoke"
    assert captured["payload"] == {
        "title": "Reconcile the document-led rollout",
        "workflow": "blitz",
        "spec": "Roll out the linked document; done when it lands.",
        "entry_surface": "harness_skill",
        "project": "yoke",
        "dry_run": False,
        "execution_instructions_considered": True,
    }

    definition = BLITZ_WORKFLOW_DEFINITION["definition"]
    assert definition["entry_surfaces"] == ["harness_skill"]
    assert definition["skill_bindings"] == [
        {
            "skill_id": "refine",
            "from_stage_id": "idea",
            "through_stage_id": "refined-idea",
        },
        {
            "skill_id": "blitz",
            "from_stage_id": "refined-idea",
            "through_stage_id": "done",
        },
    ]


def test_direct_operation_ids_are_complete():
    registered = {row["function_id"]: row for row in DIRECT_WORKFLOW_REGISTRATIONS}
    dash_ids = {
        f"direct_workflow.dash.{op}" for op in ("survey", "evidence", "escalate")
    }
    blitz_ids = {"direct_workflow.blitz.survey"}
    assert set(registered) == dash_ids | blitz_ids
    assert registered["direct_workflow.dash.survey"]["claim_required_kind"] is None
    assert registered["direct_workflow.blitz.survey"]["claim_required_kind"] is None
    assert registered["direct_workflow.dash.evidence"]["claim_required_kind"] == "item"
    assert registered["direct_workflow.dash.escalate"]["claim_required_kind"] == "item"


def test_taught_dash_and_blitz_commands_resolve_to_registered_functions():
    register_all_handlers()
    dash = _skill_corpus("dash")
    blitz = _skill_corpus("blitz")
    taught = {
        dash: {
            "items.create": "yoke dash ",
            "items.detail.get": "yoke items detail get",
            "claims.work.acquire": "yoke claims work acquire",
            "direct_workflow.dash.survey": "yoke direct-workflow dash survey",
            "claims.path.register": "yoke claims path register",
            "lifecycle.transition.execute": "yoke lifecycle transition",
            "direct_workflow.dash.evidence": "yoke direct-workflow dash evidence",
            "events.query.run": "yoke events query",
            "claims.work.release": "yoke claims work release",
            "direct_workflow.dash.escalate": "yoke direct-workflow dash escalate",
        },
        blitz: {
            "strategy.execution.get": "yoke strategy execution get",
            "direct_workflow.blitz.survey": "yoke direct-workflow blitz survey",
            "lifecycle.transition.execute": "yoke lifecycle transition",
            "strategy.coordination.append": "yoke strategy coordination append",
            "strategy.doc.replace": "yoke strategy doc replace",
            "claims.work.release": "yoke claims work release",
        },
    }
    for content, operations in taught.items():
        for function_id, command in operations.items():
            assert lookup(function_id) is not None, function_id
            assert command in content, command


def test_direct_workflow_skills_match_install_bundle():
    for skill in ("dash", "blitz"):
        canonical_root = CANONICAL / skill
        mirrored_root = BUNDLE / skill
        canonical = {
            path.relative_to(canonical_root): path.read_bytes()
            for path in canonical_root.rglob("*")
            if path.is_file()
        }
        mirrored = {
            path.relative_to(mirrored_root): path.read_bytes()
            for path in mirrored_root.rglob("*")
            if path.is_file()
        }
        assert mirrored == canonical
