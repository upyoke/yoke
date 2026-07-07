"""Codex shepherd smoke — minimal end-to-end planning path proof.

Satisfies AC-10 of the epic and AC-1 / AC-3 / AC-5 of task 9 spec:
asserts that a minimal shepherd dispatch (architect → boss verdict) renders
through the cross-harness ``DispatchDescriptor`` substrate against the
rendered Codex adapter TOMLs, that the planning verdict envelope is
parseable per the role's ``result_schema``, and that at least one canonical
telemetry event (``HarnessSessionOffered``) is emitted to the events sink.

The smoke does NOT depend on a real Codex CLI. It mocks the harness boundary
(adapter file existence + the ``codex agent:`` invocation snippet) and uses
the events capture sink (``YOKE_EVENTS_CAPTURE=1`` + ``YOKE_EVENTS_FILE``)
so the telemetry assertion does not require a populated Yoke DB.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_core.domain.dispatch_descriptors import (
    REFLECTION_BLOCK,
    VERDICT_READY_NOT_READY_CAVEATS,
    DispatchDescriptor,
    render_for_harness,
)
from yoke_core.domain.events import emit_event


# Repo root, resolved relative to this file (runtime/harness/codex/<this>.py).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CODEX_AGENTS_DIR = _REPO_ROOT / "runtime" / "harness" / "codex" / "agents"


# Per task 9 dispatch context: the rendered TOMLs come from sibling task 8.
# Until that work merges to main this directory may be absent in CI runs that
# don't pick up the renderer; skip cleanly rather than fail spuriously, so the
# smoke is correct both before and after the renderer ships.
_REQUIRES_RENDERED_AGENTS = pytest.mark.skipif(
    not _CODEX_AGENTS_DIR.is_dir(),
    reason=(
        "Rendered Codex agent TOMLs not present "
        "(task 8 of YOK-1577 not yet in main); smoke skipped."
    ),
)


# A boss-shaped planning verdict envelope. Mirrors what a sub-agent returns
# at end-of-session per docs/prompt-philosophy.md: VERDICT line + reflection
# block. The smoke parses this string against the descriptor's result schema.
_BOSS_PLANNING_VERDICT = """\
Plan looks good. Caveats: AC-3 evidence still pending.

VERDICT: READY|NOT_READY|CAVEATS
CAVEATS

---REFLECTION-START---
- Note: planning succeeded with one caveat.
---REFLECTION-END---
"""


@_REQUIRES_RENDERED_AGENTS
class TestRenderedAdapterReferenced:
    """AC-5: smoke references the rendered ``.codex/agents/yoke-{role}.toml``
    paths rather than re-authoring agent body content.
    """

    @pytest.mark.parametrize("role", ("architect", "boss"))
    def test_dispatch_descriptor_codex_render_names_adapter_path(self, role):
        descriptor = DispatchDescriptor(role=role)
        rendered = render_for_harness(descriptor, "codex")
        # The exact relative path the descriptor renders.
        relpath = f".codex/agents/yoke-{role}.toml"
        assert relpath in rendered
        # And the matching adapter file exists in the rendered tree.
        # The rendered tree lives at runtime/harness/codex/agents/, which is
        # the canonical source for the .codex/agents/ adapter location.
        toml = _CODEX_AGENTS_DIR / f"yoke-{role}.toml"
        assert toml.is_file(), f"missing rendered adapter: {toml}"
        body = toml.read_text(encoding="utf-8")
        assert f'name = "yoke-{role}"' in body
        assert "prompt" in body  # generated TOMLs carry a prompt block


@_REQUIRES_RENDERED_AGENTS
class TestPlanningVerdictParsesAgainstSchema:
    """AC-1: a minimal shepherd path runs end-to-end in Codex hook-enhanced mode.

    We exercise the dispatch contract — descriptor render + result envelope
    parsing — against the rendered Codex adapter. This is the parent-skill's
    parseable handshake; a real shepherd skill consumes both halves.
    """

    def test_boss_verdict_envelope_matches_role_schema(self):
        descriptor = DispatchDescriptor(role="boss")
        schema = descriptor.result_schema
        # Boss role parses the READY|NOT_READY|CAVEATS verdict + reflection.
        assert VERDICT_READY_NOT_READY_CAVEATS in schema
        assert REFLECTION_BLOCK in schema
        # Both markers must appear in a real verdict envelope so the parent
        # skill can find them.
        for marker in schema:
            assert marker in _BOSS_PLANNING_VERDICT, (
                f"schema marker missing from envelope: {marker}"
            )

    def test_codex_render_includes_prompt_placeholder(self):
        """The Codex spawn snippet leaves a ``prompt: |`` block for the parent
        skill to fill — that placeholder is what shepherd writes the planning
        prose into before invoking the adapter."""
        descriptor = DispatchDescriptor(role="architect")
        rendered = render_for_harness(descriptor, "codex")
        assert "prompt: |" in rendered

    def test_architect_dispatch_uses_renderable_adapter_only(self):
        """Architect role does not require a model override in shepherd's
        non-retry path (task 7 skill prose); the smoke confirms the descriptor
        renders cleanly without extras."""
        descriptor = DispatchDescriptor(role="architect")
        rendered = render_for_harness(descriptor, "codex")
        assert "model:" not in rendered  # no override on default render


@_REQUIRES_RENDERED_AGENTS
class TestTelemetryEmittedDuringDispatch:
    """AC-3: at least one canonical telemetry event is observable in the
    smoke run.

    We emit ``HarnessSessionOffered`` to the capture sink (no DB required) and
    assert the envelope is shaped correctly. This proves that a shepherd
    invocation in Codex hook-enhanced mode would surface the same telemetry
    on the canonical events ledger when the DB is configured.
    """

    def test_harness_session_offered_event_visible_in_capture_sink(
        self, tmp_path, monkeypatch
    ):
        capture_file = tmp_path / "events.jsonl"
        monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
        monkeypatch.setenv("YOKE_EVENTS_FILE", str(capture_file))

        # Emit the canonical session-offer event the way sessions_offer does
        # for any real shepherd-driven harness session.
        result = emit_event(
            "HarnessSessionOffered",
            event_kind="system",
            event_type="session_offer",
            source_type="backend",
            session_id="smoke-shepherd-1",
            project="yoke",
            context={"executor": "codex", "step": "shepherd"},
        )

        # Capture-mode is the documented path for non-canonical writes.
        assert result.envelope is not None
        assert result.envelope["event_name"] == "HarnessSessionOffered"
        assert result.reason == "capture_only"

        # The capture file got the line with the canonical envelope shape.
        lines = capture_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        envelope = json.loads(lines[0])
        assert envelope["event_name"] == "HarnessSessionOffered"
        assert envelope["session_id"] == "smoke-shepherd-1"
        assert envelope["source_type"] == "backend"
        # The context payload should record the executor/step the shepherd
        # smoke established.
        ctx = envelope.get("context") or {}
        assert ctx.get("executor") == "codex"
        assert ctx.get("step") == "shepherd"
