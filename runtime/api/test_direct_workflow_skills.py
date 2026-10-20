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


def test_dash_skill_carries_the_end_to_end_execution_contract():
    content = " ".join(_skill_corpus("dash").split())
    for required in (
        "yoke direct-workflow dash survey",
        "yoke direct-workflow worktree prepare ITEM --workflow dash",
        "Work only in the returned `worktree_path`",
        "reviewing-implementation",
        "yoke direct-workflow dash evidence",
        "yoke direct-workflow dash escalate",
        # The claim is acquired before any survey or edit and held through
        # delivery; a release wait keeps it.
        "Claim before any survey or edit",
        'yoke claims work acquire --item ITEM --reason "Dash execution"',
        "Delivery owed: keep the claim and lane",
        'yoke claims work release --item ITEM --reason "Dash completed"',
        "Each survey replaces the whole touch set",
        "list every concrete file",
        # Merging is a named operation, never a hand-authored git merge.
        "yoke merge item ITEM",
        "Never hand-merge",
    ):
        assert required in content, required
    # The unnamed "merge it through the project's merge path" instruction is
    # what sent agents to hand-authored git merges; it must not come back.
    assert "through the project's normal protected merge path" not in content
    # `yoke say --steering` stays legal: it reaches the steering seat.
    assert "yoke say --session" not in content
    assert "yoke say --item" not in content
    # Unconditional "finally release after merge" teaching contradicts the
    # terminal transition that already releases the claim and lane.
    assert "Finally release the item work claim:" not in content


def test_dash_commits_before_every_sha_bound_case():
    verify = " ".join((CANONICAL / "dash" / "verify.md").read_text().split())
    commit_rule = "Commit, then re-survey the actual touched files"
    assert verify.index(commit_rule) < verify.index("yoke qa case run")
    assert "before each SHA-bound case" in verify
    assert "any tree change reruns the affected cases" in verify


def test_dash_rechecks_keep_survey_contacts_advisory():
    skill = " ".join((CANONICAL / "dash/survey-and-isolate.md").read_text().split())
    corpus = _skill_corpus("dash")
    for retired_stop in (
        "If the survey is blocked, do not commit or run the case.",
        "A stale or newly-blocked survey is a coordination stop",
        "If the result is blocked, do not merge.",
    ):
        assert retired_stop not in corpus
    for required in (
        "Contacts are advisory",
        "independent edits proceed",
        "ordered ones wait for the holder's merge",
        "yoke say --steering",
        "register every file before prepare",
    ):
        assert required in skill, required
    assert "release the work claim" not in skill


def test_blitz_skill_carries_slice_and_document_completion_contract():
    content = _skill_corpus("blitz")
    normalized = " ".join(content.split())
    for required in (
        "yoke strategy execution get",
        "yoke direct-workflow blitz survey",
        "yoke strategy coordination append",
        "- Completed:",
        "- Changed:",
        "- Remaining:",
        "- Parent reconciliation:",
        "Merge worker commits only inside the integration lane",
        # Slice merges route through the same named boundary as Dash, and
        # leave the item non-terminal until the document completes.
        "yoke watch merge --print-streaming-pair merge-item -- ITEM --skip-status --wait",
    ):
        assert required in normalized, required
    assert "through the project's protected merge path" not in content


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

    idea = _skill_corpus("idea")
    infer = (ROOT / ".agents/skills/yoke/idea/infer-and-create.md").read_text()
    # Install/dogfood corpus (stub at docs/workflows.md only points here).
    workflows = (ROOT / ".yoke/docs/workflows/index.md").read_text()
    assert "--workflow issue|epic|blitz|task" in idea
    assert "--entry-surface harness_skill" in infer
    assert "Blitz: refinement links one execution strategy doc" in infer
    assert "blitz" in workflows.lower()
    assert "strategy doc" in workflows.lower()
    refine = (
        ROOT / ".agents/skills/yoke/refine/blitz-execution-document.md"
    ).read_text()
    assert "yoke strategy execution link" in refine


def test_operator_discovery_and_direct_operation_ids_are_complete():
    root_skill = (ROOT / ".agents/skills/yoke/SKILL.md").read_text()
    help_skill = (ROOT / ".agents/skills/yoke/help/SKILL.md").read_text()
    for content in (root_skill, help_skill):
        assert "/yoke dash" in content
        assert "/yoke blitz" in content
    assert "--workflow issue\\|epic\\|blitz\\|task" in help_skill

    registered = {row["function_id"]: row for row in DIRECT_WORKFLOW_REGISTRATIONS}
    dash_ids = {
        f"direct_workflow.dash.{op}" for op in ("survey", "evidence", "escalate")
    }
    blitz_ids = {"direct_workflow.blitz.survey"}
    assert set(registered) == dash_ids | blitz_ids

    dash = _skill_corpus("dash")
    for op in ("survey", "evidence", "escalate"):
        assert f"yoke direct-workflow dash {op}" in dash
    blitz = _skill_corpus("blitz")
    assert "yoke direct-workflow blitz survey" in blitz
    assert registered["direct_workflow.dash.survey"]["claim_required_kind"] is None
    assert registered["direct_workflow.blitz.survey"]["claim_required_kind"] is None
    assert registered["direct_workflow.dash.evidence"]["claim_required_kind"] == "item"
    assert registered["direct_workflow.dash.escalate"]["claim_required_kind"] == "item"
    for content in (dash, blitz):
        assert "direct_workflow.worktree.prepare" not in content


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

    for content, workflow in ((dash, "dash"), (blitz, "blitz")):
        assert (
            f"yoke direct-workflow worktree prepare ITEM --workflow {workflow}"
            in content
        )
        assert "direct_workflow.worktree.prepare" not in content


def test_dash_close_out_surfaces_session_guardrail_denials():
    content = (CANONICAL / "dash/close-out.md").read_text()
    step = content[content.index("guardrail denials") :]
    assert "file field notes for any unrecorded" in step
    assert (
        "yoke events query --session SESSION_ID --event-name HarnessToolCallDenied"
        in step
    )


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
