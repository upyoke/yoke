"""Dash and Blitz skill distribution invariants."""

from __future__ import annotations

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


ROOT = Path(__file__).parents[2]
BUNDLE = (
    ROOT
    / "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke"
)
CANONICAL = ROOT / ".agents/skills/yoke"


def _skill_corpus(skill: str) -> str:
    directory = CANONICAL / skill
    return "\n".join(path.read_text() for path in sorted(directory.glob("*.md")))


def test_dash_skill_carries_the_end_to_end_execution_contract():
    content = _skill_corpus("dash")
    for required in (
        "direct-workflow dash survey",
        "direct-workflow worktree prepare",
        "reviewing-implementation",
        "direct-workflow dash evidence",
        "direct-workflow dash escalate",
        "Registered work and path claims always win",
        "`work_claim_activation` gate",
        "may already release the item work claim",
        "registered Dash worktree lane",
        # The item work claim is acquired up front (step 1), before any
        # survey/edit work. Close-out release is conditional: merge/done may
        # already have released the claim and removed the lane.
        "Claim the item first.",
        'yoke claims work acquire --item ITEM --reason "Dash execution"',
        "Only release when a claim remains, or when",
        'yoke claims work release --item ITEM --reason "Dash completed"',
        "Every survey call replaces the entire stored touch set",
        "narrow it to the complete",
        "concrete file set before preparation",
        "rg --files",
        "send_message_to_thread",
        "invent or guess a prefix",
        "No environment override is required",
        # Merging is a named operation, never a hand-authored git merge.
        "yoke merge item ITEM",
    ):
        assert required in content
    # The merge step names one command. The unnamed "merge it through the
    # project's merge path" instruction is what sent agents to hand-authored
    # git merges, and must not come back.
    assert "through the project's normal protected merge path" not in content
    assert "yoke say" not in content
    # Unconditional "finally release after merge" teaching contradicts the
    # terminal transition that already releases the claim and lane.
    assert "Finally release the item work claim:" not in content
    assert "/yoke idea" in content
    assert "does not route through `/yoke idea`" in content


def test_dash_commits_before_every_sha_bound_case():
    content = (CANONICAL / "dash/verification-and-close.md").read_text()
    commit_rule = "Commit before every SHA-bound QA case."
    assert commit_rule in content
    assert content.index(commit_rule) < content.index("yoke qa case run")
    assert "`worktree_run`" in content
    assert "`ci_run`" in content
    assert "running it before the commit" in content
    assert "rerun every affected SHA-bound case" in content


def test_blitz_skill_carries_slice_and_document_completion_contract():
    content = (ROOT / ".agents/skills/yoke/blitz/SKILL.md").read_text()
    for required in (
        "strategy execution get",
        "direct-workflow blitz survey",
        "strategy coordination append",
        "what was completed",
        "what changed",
        "what remains",
        "parent strategy was reconciled",
        "doc_completion",
        "registered worker worktree",
        "terminal transition releases the item-owned document claim",
        # Slice merges route through the same named boundary as Dash, and
        # leave the item non-terminal until the document completes.
        "yoke merge item ITEM --skip-status",
    ):
        assert required in content
    assert "through the project's protected merge path" not in content


def test_idea_to_blitz_route_dispatches_the_typed_create_payload(monkeypatch):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(items_create, "dispatch_and_emit", _dispatch)

    assert items_create.items_create([
        "Reconcile the document-led rollout",
        "blitz",
        "--entry-surface",
        "harness_skill",
        "--project",
        "yoke",
    ]) == 0
    assert captured["function_id"] == "items.create"
    assert captured["target"].kind == "global"
    assert captured["target"].project_id == "yoke"
    assert captured["payload"] == {
        "title": "Reconcile the document-led rollout",
        "workflow": "blitz",
        "entry_surface": "harness_skill",
        "project": "yoke",
        "dry_run": False,
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

    idea = (ROOT / ".agents/skills/yoke/idea/SKILL.md").read_text()
    infer = (
        ROOT / ".agents/skills/yoke/idea/infer-and-create.md"
    ).read_text()
    # Install/dogfood corpus (stub at docs/workflows.md only points here).
    workflows = (ROOT / ".yoke/docs/workflows.md").read_text()
    for content in (idea, infer):
        assert "/yoke idea --workflow blitz" in content
        assert "harness_skill" in content
        assert "exactly one execution strategy document" in content
    assert "blitz" in workflows.lower()
    assert "strategy doc" in workflows.lower()
    assert "strategy.execution.link" in infer


def test_operator_discovery_and_direct_operation_ids_are_complete():
    root_skill = (ROOT / ".agents/skills/yoke/SKILL.md").read_text()
    help_skill = (ROOT / ".agents/skills/yoke/help/SKILL.md").read_text()
    for content in (root_skill, help_skill):
        assert "/yoke dash" in content
        assert "/yoke blitz" in content
        assert "--workflow" in content
        assert "blitz" in content

    registered = {
        row["function_id"]: row
        for row in DIRECT_WORKFLOW_REGISTRATIONS
    }
    dash_ids = {
        "direct_workflow.dash.survey",
        "direct_workflow.dash.evidence",
        "direct_workflow.dash.escalate",
    }
    blitz_ids = {"direct_workflow.blitz.survey"}
    assert set(registered) == dash_ids | blitz_ids

    dash = _skill_corpus("dash")
    for function_id in dash_ids:
        assert function_id in dash
    blitz = (ROOT / ".agents/skills/yoke/blitz/SKILL.md").read_text()
    for function_id in blitz_ids:
        assert function_id in blitz
    assert registered["direct_workflow.dash.survey"][
        "claim_required_kind"
    ] is None
    assert registered["direct_workflow.blitz.survey"][
        "claim_required_kind"
    ] is None
    assert registered["direct_workflow.dash.evidence"][
        "claim_required_kind"
    ] == "item"
    assert registered["direct_workflow.dash.escalate"][
        "claim_required_kind"
    ] == "item"
    for content in (dash, blitz):
        assert "retained tool-shaped operation" in content
        assert "has no registered" in content
        assert "direct_workflow.worktree.prepare" not in content


def test_refine_blitz_path_links_one_document_and_hands_off():
    refine = (ROOT / ".agents/skills/yoke/refine/SKILL.md").read_text()
    protocol = (
        ROOT / ".agents/skills/yoke/refine/update-protocol.md"
    ).read_text()
    handoff = (
        ROOT / ".agents/skills/yoke/refine/blitz-execution-document.md"
    ).read_text()

    assert "ITEM_NEXT_SKILL=blitz" in refine
    assert "blitz-execution-document.md" in refine
    assert "strategy.execution.link" in protocol
    for required in (
        "Select exactly one document",
        "strategy.execution.link",
        "yoke strategy execution link",
        "strategy.execution.get",
        "yoke strategy execution get",
        "execution.execution_document.slug",
        "Next step: /yoke blitz",
    ):
        assert required in handoff


def test_taught_dash_and_blitz_commands_are_function_id_first():
    register_all_handlers()
    dash = _skill_corpus("dash")
    blitz = (ROOT / ".agents/skills/yoke/blitz/SKILL.md").read_text()
    taught = {
        dash: {
            "items.create": "yoke dash ",
            "items.detail.get": "yoke items detail get",
            "claims.work.acquire": "yoke claims work acquire",
            "direct_workflow.dash.survey": (
                "yoke direct-workflow dash survey"
            ),
            "claims.path.register": "yoke claims path register",
            "lifecycle.transition.execute": "yoke lifecycle transition",
            "direct_workflow.dash.evidence": (
                "yoke direct-workflow dash evidence"
            ),
            "claims.work.release": "yoke claims work release",
            "direct_workflow.dash.escalate": (
                "yoke direct-workflow dash escalate"
            ),
        },
        blitz: {
            "items.detail.get": "yoke items detail get",
            "strategy.execution.get": "yoke strategy execution get",
            "strategy.doc.get": "yoke strategy doc get",
            "direct_workflow.blitz.survey": (
                "yoke direct-workflow blitz survey"
            ),
            "lifecycle.transition.execute": "yoke lifecycle transition",
            "strategy.coordination.append": (
                "yoke strategy coordination append"
            ),
            "strategy.doc.replace": "yoke strategy doc replace",
            "strategy.claim.release": "yoke strategy claim release",
            "claims.work.release": "yoke claims work release",
        },
    }
    for content, operations in taught.items():
        for function_id, command in operations.items():
            assert lookup(function_id) is not None, function_id
            assert content.index(function_id) < content.index(command)

    for content, workflow in ((dash, "dash"), (blitz, "blitz")):
        assert (
            f"yoke direct-workflow worktree prepare ITEM --workflow {workflow}"
            in content
        )
        assert "retained tool-shaped operation" in content
        assert "direct_workflow.worktree.prepare" not in content


def test_direct_workflow_skills_match_install_bundle():
    for skill in ("dash", "blitz"):
        canonical_root = CANONICAL / skill
        mirrored_root = BUNDLE / skill
        canonical = {
            path.relative_to(canonical_root): path.read_bytes()
            for path in canonical_root.rglob("*") if path.is_file()
        }
        mirrored = {
            path.relative_to(mirrored_root): path.read_bytes()
            for path in mirrored_root.rglob("*") if path.is_file()
        }
        assert mirrored == canonical
