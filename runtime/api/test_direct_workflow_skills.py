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
from runtime.api.skill_doc_regressions_test_helpers import _read_skill_corpus


ROOT = Path(__file__).parents[2]
_TREE = "packages/yoke-core/src/yoke_core/install_bundle_tree"
BUNDLE = ROOT / _TREE / ".agents/skills/yoke"
CANONICAL = ROOT / ".agents/skills/yoke"


def _skill_corpus(skill: str) -> str:
    return _read_skill_corpus(CANONICAL / skill)


def _reference(skill: str) -> str:
    return (CANONICAL / skill / "function-reference.md").read_text()


def test_dash_skill_carries_the_end_to_end_execution_contract():
    content = _skill_corpus("dash")
    for required in (
        "direct-workflow dash survey",
        "direct-workflow worktree prepare",
        "reviewing-implementation",
        "direct-workflow dash evidence",
        "direct-workflow dash escalate",
        "Survey contacts are advisories",
        "`work_claim_activation` gate",
        "may already release the item work claim",
        "registered Dash worktree lane",
        # The claim is acquired up front, before any survey/edit work; its
        # release is conditional on what merge/done already did.
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
    # The unnamed "merge it through the project's merge path" instruction is
    # what sent agents to hand-authored git merges; it must not come back.
    assert "through the project's normal protected merge path" not in content
    # A path-claim holder is reached with the harness task-messaging tool,
    # never by addressing a session or item over the message plane.
    # `yoke say --steering` stays legal: it reaches the steering seat.
    assert "yoke say --session" not in content
    assert "yoke say --item" not in content
    # Unconditional "finally release after merge" teaching contradicts the
    # terminal transition that already releases the claim and lane.
    assert "Finally release the item work claim:" not in content
    assert "/yoke idea" in content
    assert "does not route through `/yoke idea`" in content


def test_dash_commits_before_every_sha_bound_case():
    content = _skill_corpus("dash")
    commit_rule = "Commit before every SHA-bound QA case."
    assert commit_rule in content
    assert content.index(commit_rule) < content.index("yoke qa case run")
    assert "`worktree_run`" in content
    assert "`ci_run`" in content
    assert "running it before the commit" in content
    assert "rerun every affected SHA-bound case" in content


def test_dash_rechecks_keep_survey_contacts_advisory():
    skill = (CANONICAL / "dash/survey-and-isolate.md").read_text()
    corpus = close = _skill_corpus("dash")
    for retired_stop in (
        "If the survey is blocked, do not commit or run the case.",
        "A stale or newly-blocked survey is a coordination stop",
        "If the result is blocked, do not merge.",
    ):
        assert retired_stop not in corpus
    assert "A reported overlap remains advisory" in close
    assert "does not block the transition" in skill
    contact_rules = skill.split("For every reported survey contact", 1)[1].split(
        "Selected path-claim posture", 1
    )[0]
    contact_rules = " ".join(contact_rules.split())
    for required in (
        "ask an addressable holder for that evidence",
        "wait for the holding work to land",
        "re-run the survey",
        "release the work claim",
        "present the holder, paths, and evidence to the operator",
    ):
        assert required in contact_rules
    for path_claim_remedy in (
        "coordination_only",
        "activation dependency",
        "coordinate with",
        "tighten with claims",
        "register or widen",
    ):
        assert path_claim_remedy not in contact_rules


def test_blitz_skill_carries_slice_and_document_completion_contract():
    content = _skill_corpus("blitz")
    normalized = " ".join(content.split())
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
        "terminal transition atomically archives the linked execution document",
        "shared live document stays active",
        "parent document is never archived",
        "GATE_BLITZ_DOCUMENT_ARCHIVE_FAILED",
        # Slice merges route through the same named boundary as Dash, and
        # leave the item non-terminal until the document completes.
        "yoke watch merge --print-streaming-pair merge-item -- ITEM --skip-status --wait",
    ):
        assert required in normalized
    assert "verified route gets the background subscription" in normalized
    assert "no route or an unknown answer gets one foreground invocation" in normalized
    assert "prints \u2014 and never runs \u2014 the shape" in normalized
    assert "through the project's protected merge path" not in content


def test_idea_to_blitz_route_dispatches_the_typed_create_payload(monkeypatch):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(items_create, "dispatch_and_emit", _dispatch)

    assert (
        items_create.items_create(
            [
                "Reconcile the document-led rollout",
                "blitz",
                "--entry-surface",
                "harness_skill",
                "--project",
                "yoke",
                "--execution-instructions-considered",
            ]
        )
        == 0
    )
    assert captured["function_id"] == "items.create"
    assert captured["target"].kind == "global"
    assert captured["target"].project_id == "yoke"
    assert captured["payload"] == {
        "title": "Reconcile the document-led rollout",
        "workflow": "blitz",
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
        assert "yoke task" in content
        assert "/yoke blitz" in content
        assert "--workflow" in content
        assert "blitz" in content

    registered = {row["function_id"]: row for row in DIRECT_WORKFLOW_REGISTRATIONS}
    dash_ids = {f"direct_workflow.dash.{op}" for op in ("survey", "evidence", "escalate")}
    blitz_ids = {"direct_workflow.blitz.survey"}
    assert set(registered) == dash_ids | blitz_ids

    dash = _skill_corpus("dash")
    for function_id in dash_ids:
        assert function_id in dash
    blitz = _skill_corpus("blitz")
    for function_id in blitz_ids:
        assert function_id in blitz
    assert registered["direct_workflow.dash.survey"]["claim_required_kind"] is None
    assert registered["direct_workflow.blitz.survey"]["claim_required_kind"] is None
    assert registered["direct_workflow.dash.evidence"]["claim_required_kind"] == "item"
    assert registered["direct_workflow.dash.escalate"]["claim_required_kind"] == "item"
    for content in (dash, blitz):
        assert "retained tool-shaped operation" in content
        assert "has no registered" in content
        assert "direct_workflow.worktree.prepare" not in content


def test_refine_blitz_path_links_one_document_and_hands_off():
    refine = (ROOT / ".agents/skills/yoke/refine/SKILL.md").read_text()
    protocol = (ROOT / ".agents/skills/yoke/refine/update-protocol.md").read_text()
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
    blitz = _skill_corpus("blitz")
    taught = {
        dash: {
            "items.create": "yoke dash ",
            "items.detail.get": "yoke items detail get",
            "claims.work.acquire": "yoke claims work acquire",
            "direct_workflow.dash.survey": ("yoke direct-workflow dash survey"),
            "claims.path.register": "yoke claims path register",
            "lifecycle.transition.execute": "yoke lifecycle transition",
            "direct_workflow.dash.evidence": ("yoke direct-workflow dash evidence"),
            "sessions.identity": "yoke sessions identity",
            "events.query.run": "yoke events query",
            "claims.work.release": "yoke claims work release",
            "direct_workflow.dash.escalate": ("yoke direct-workflow dash escalate"),
        },
        blitz: {
            "items.detail.get": "yoke items detail get",
            "strategy.execution.get": "yoke strategy execution get",
            "strategy.doc.get": "yoke strategy doc get",
            "direct_workflow.blitz.survey": ("yoke direct-workflow blitz survey"),
            "lifecycle.transition.execute": "yoke lifecycle transition",
            "strategy.coordination.append": ("yoke strategy coordination append"),
            "strategy.doc.replace": "yoke strategy doc replace",
            "strategy.claim.release": "yoke strategy claim release",
            "claims.work.release": "yoke claims work release",
        },
    }
    reference_by_content = {dash: _reference("dash"), blitz: _reference("blitz")}
    for content, operations in taught.items():
        reference = reference_by_content[content]
        for function_id, command in operations.items():
            assert lookup(function_id) is not None, function_id
            assert function_id in content
            # Dash spreads its phases over files, so "function id first" is a
            # per-teaching-site property, not one of the concatenated corpus.
            source = reference if function_id in reference else content
            assert source.index(function_id) < source.index(command), function_id

    for content, workflow in ((dash, "dash"), (blitz, "blitz")):
        assert (
            f"yoke direct-workflow worktree prepare ITEM --workflow {workflow}"
            in content
        )
        assert "retained tool-shaped operation" in content
        assert "direct_workflow.worktree.prepare" not in content


def test_dash_close_out_surfaces_session_guardrail_denials():
    content = (CANONICAL / "dash/close-out.md").read_text()
    step = content[content.index("## Surface this session's guardrail denials") :]
    for required in (
        "HarnessToolCallDenied",
        "sessions.identity",
        "yoke sessions identity",
        "events.query.run",
        "yoke events query",
        "check_id",
        "command_snippet",
        "does not block",
        "say nothing extra",
        "field-note",
    ):
        assert required in step
    assert "does not correlate" in step.lower() or ("Do not correlate denials" in step)


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
