"""Cursor QA-walker rendering and dispatch capability guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import qa_plan_execution_cli
from yoke_core.domain.agents_render_cursor import (
    CURSOR_QA_WALKER_POSTURE_MISSING_REASON,
    CURSOR_QA_WALKER_READONLY_REASON,
    CursorAgentCapabilityError,
    render_cursor_agent,
)
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError


def _canonical_walker(tmp_path: Path, *, sidecar: str) -> Path:
    canonical = tmp_path / "runtime" / "agents"
    canonical.mkdir(parents=True)
    (canonical / "qa-walker.md").write_text(
        "Walk the supplied mission and return ranked findings.\n",
        encoding="utf-8",
    )
    (canonical / "qa-walker.cursor.json").write_text(
        sidecar,
        encoding="utf-8",
    )
    return canonical


def _mission_result() -> dict:
    return {
        "review_bundle": {
            "dispatch": {
                "walker_dispatches": [
                    {
                        "executor": "informed_subagent",
                        "subagent_type": "yoke-qa-walker",
                    }
                ]
            }
        }
    }


def _write_discovered_adapter(tmp_path: Path, *, readonly: bool) -> None:
    adapter = tmp_path / ".cursor" / "agents" / "yoke-qa-walker.md"
    adapter.parent.mkdir(parents=True)
    adapter.write_text(
        "---\n"
        "name: yoke-qa-walker\n"
        f"readonly: {str(readonly).lower()}\n"
        "---\n"
        "Walk the mission.\n",
        encoding="utf-8",
    )


def test_rendered_cursor_walker_is_explicitly_write_capable(
    tmp_path: Path,
) -> None:
    canonical = _canonical_walker(
        tmp_path,
        sidecar=('{"name":"yoke-qa-walker","description":"Walk QA","readonly":false}'),
    )

    rendered = render_cursor_agent(canonical, "qa-walker")

    assert "\nreadonly: false\n" in rendered


def test_renderer_refuses_an_implicit_walker_write_posture(tmp_path: Path) -> None:
    canonical = _canonical_walker(
        tmp_path,
        sidecar='{"name":"yoke-qa-walker","description":"Walk QA"}',
    )

    with pytest.raises(
        CursorAgentCapabilityError,
        match=CURSOR_QA_WALKER_POSTURE_MISSING_REASON,
    ):
        render_cursor_agent(canonical, "qa-walker")


def test_dispatch_refuses_a_readonly_cursor_walker_with_named_recovery(
    tmp_path: Path,
) -> None:
    _write_discovered_adapter(tmp_path, readonly=True)

    with pytest.raises(
        QaPlanExecutionError,
        match=CURSOR_QA_WALKER_READONLY_REASON,
    ) as refusal:
        qa_plan_execution_cli._require_walker_dispatch_capability(
            _mission_result(),
            harness_id="cursor",
            target_root=tmp_path,
        )

    assert "yoke agents render --target-root <checkout>" in str(refusal.value)


def test_dispatch_accepts_a_write_capable_cursor_walker(tmp_path: Path) -> None:
    _write_discovered_adapter(tmp_path, readonly=False)

    qa_plan_execution_cli._require_walker_dispatch_capability(
        _mission_result(),
        harness_id="cursor",
        target_root=tmp_path,
    )


def test_dispatch_reads_the_adapter_from_the_cursor_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_discovered_adapter(tmp_path, readonly=True)
    monkeypatch.setenv("YOKE_ROOT", str(tmp_path))

    with pytest.raises(
        QaPlanExecutionError,
        match=CURSOR_QA_WALKER_READONLY_REASON,
    ):
        qa_plan_execution_cli._require_walker_dispatch_capability(
            _mission_result(),
            harness_id="cursor",
        )
