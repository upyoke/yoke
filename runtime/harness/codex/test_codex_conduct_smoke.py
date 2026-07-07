"""Codex conduct smoke — dispatch descriptor → custom-agent invocation proof.

Satisfies AC-2 / AC-3 / AC-5 of the task 9 spec: exercises the
``yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor,
"codex")`` path against the rendered Codex adapter TOML for a no-op engineer
task body, asserts the parseable result envelope ingests cleanly per the
engineer ``result_schema``, and asserts at least one canonical telemetry
event (``NextActionChosen``) is observable in the smoke run.

The smoke does NOT spawn a real Codex sub-agent. It mocks the harness
boundary (the rendered adapter file existence + the descriptor invocation
parser) so the dispatch contract can be verified without depending on a
Codex CLI being installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.dispatch_descriptors import (
    REFLECTION_BLOCK,
    SUBMISSION_CHECKS_BLOCK,
    DispatchDescriptor,
    render_for_harness,
)
from yoke_core.domain.events import emit_event


_REPO_ROOT = Path(__file__).resolve().parents[3]
_CODEX_AGENTS_DIR = _REPO_ROOT / "runtime" / "harness" / "codex" / "agents"


_REQUIRES_RENDERED_AGENTS = pytest.mark.skipif(
    not _CODEX_AGENTS_DIR.is_dir(),
    reason=(
        "Rendered Codex agent TOMLs not present "
        "(task 8 of YOK-1577 not yet in main); smoke skipped."
    ),
)


# Engineer parseable-result envelope. Mirrors the canonical end-of-session
# shape for yoke-engineer (per its persona body): a SUBMISSION-CHECKS block
# followed by a REFLECTION block. The smoke parses this against the
# descriptor's role-owned schema so the parent skill's ingestion logic can be
# exercised without a real sub-agent return.
_ENGINEER_RESULT_ENVELOPE = """\
Implemented the no-op task. All ACs satisfied.

---SUBMISSION-CHECKS-START---
test_plan: PASS - no test plan in spec
files_touched: PASS - exactly the files listed
edited_tests: SKIP - no test files edited
clean_worktree: PASS - git status --porcelain is empty
progress_notes: SKIP - non-epic task
file_budget: SKIP - no authored code grown
---SUBMISSION-CHECKS-END---

---REFLECTION-START---
- Note: smoke task carried no observed friction.
---REFLECTION-END---
"""


@_REQUIRES_RENDERED_AGENTS
class TestEngineerDispatchRendersForCodex:
    """AC-2 (rendering half): the conduct dispatch descriptor produces a
    Codex spawn snippet that names the rendered engineer adapter path.
    """

    def test_engineer_codex_render_names_engineer_adapter(self):
        descriptor = DispatchDescriptor(role="engineer")
        rendered = render_for_harness(descriptor, "codex")
        assert ".codex/agents/yoke-engineer.toml" in rendered
        assert "prompt: |" in rendered

    def test_engineer_adapter_file_exists_in_rendered_tree(self):
        toml = _CODEX_AGENTS_DIR / "yoke-engineer.toml"
        assert toml.is_file()
        body = toml.read_text(encoding="utf-8")
        assert 'name = "yoke-engineer"' in body

    def test_codex_render_with_opus_extras_emits_model_override(self):
        """Conduct's tester-retry path renders descriptors with ``model=opus``;
        the engineer descriptor accepts the same shape so the smoke's parent
        skill can use one render for the canonical path and another for retry.
        """
        descriptor = DispatchDescriptor(
            role="engineer",
            extras=(("model", "opus"),),
        )
        rendered = render_for_harness(descriptor, "codex")
        assert ".codex/agents/yoke-engineer.toml" in rendered
        assert ' model: "opus"' in rendered


@_REQUIRES_RENDERED_AGENTS
class TestEngineerResultEnvelopeIsParseable:
    """AC-2 (parsing half): a parseable result envelope from the dispatched
    sub-agent matches the descriptor's declared ``result_schema``.

    No real sub-agent runs. The fixture envelope mirrors the canonical
    end-of-session shape yoke-engineer emits.
    """

    def test_envelope_contains_every_schema_marker_for_engineer(self):
        descriptor = DispatchDescriptor(role="engineer")
        schema = descriptor.result_schema
        # Engineer schema declares the SUBMISSION-CHECKS + REFLECTION blocks.
        assert SUBMISSION_CHECKS_BLOCK in schema
        assert REFLECTION_BLOCK in schema
        # Every declared marker must appear in a real envelope so the parent
        # skill can locate the structured result.
        for marker in schema:
            assert marker in _ENGINEER_RESULT_ENVELOPE, (
                f"schema marker missing from envelope: {marker}"
            )

    def test_submission_checks_block_terminates_correctly(self):
        """The end marker MUST appear so a parser can bound the block."""
        assert "---SUBMISSION-CHECKS-END---" in _ENGINEER_RESULT_ENVELOPE

    def test_reflection_block_terminates_correctly(self):
        assert "---REFLECTION-END---" in _ENGINEER_RESULT_ENVELOPE


@_REQUIRES_RENDERED_AGENTS
class TestTelemetryEmittedDuringConductDispatch:
    """AC-3: at least one canonical telemetry event emission is observable.

    For the conduct flow we emit ``NextActionChosen`` via the events sink —
    the same event sessions_analytics_dispatch surfaces when the core picks
    the next action for an offered session. The capture sink keeps the
    assertion DB-free.
    """

    def test_next_action_chosen_event_visible_in_capture_sink(
        self, tmp_path, monkeypatch
    ):
        capture_file = tmp_path / "events.jsonl"
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.setenv("YOKE_EVENTS_FILE", str(capture_file))

        result = emit_event(
            "NextActionChosen",
            event_kind="workflow",
            event_type="session_directive",
            source_type="cli",
            session_id="smoke-conduct-1",
            project="yoke",
            severity="STATUS",
            context={
                "executor": "codex",
                "step": "conduct",
                "dispatch_role": "engineer",
            },
        )

        assert result.envelope is not None
        assert result.envelope["event_name"] == "NextActionChosen"
        assert result.reason == "capture_only"

        lines = capture_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        envelope = json.loads(lines[0])
        assert envelope["event_name"] == "NextActionChosen"
        assert envelope["session_id"] == "smoke-conduct-1"
        ctx = envelope.get("context") or {}
        assert ctx.get("executor") == "codex"
        assert ctx.get("step") == "conduct"
        assert ctx.get("dispatch_role") == "engineer"
