"""The code event catalog covers every discoverable emitter and renders stably."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.event_catalog import EVENT_CATALOG
from yoke_core.domain.event_catalog_render import (
    APPENDIX_SENTINEL,
    EVENT_CATALOG_RELPATH,
    catalog_appendix,
    render_catalog_text,
    render_event_catalog,
    resolve_repo_root,
)
from yoke_core.domain.events_registry_discovery import cmd_registry_discover
from yoke_core.engines.doctor_hc_db_events_registry import EXPECTED_LOW_CADENCE

_REPO_ROOT = Path(__file__).resolve().parents[3]

HOOK_RUNNER_TELEMETRY_EVENTS = (
    # (name, event_type, severity)
    ("HookDispatchTelemetry", "hook_dispatch", "INFO"),
    ("HookExecutionFailed", "hook_execution_failure", "WARN"),
    ("HookGuardrailEvaluated", "hook_guardrail_evaluated", "DEBUG"),
)


def test_every_discovered_call_site_has_a_catalog_row() -> None:
    discovered = {
        line.split("|", 1)[0]: line.split("|", 1)[1]
        for line in cmd_registry_discover(str(_REPO_ROOT)).splitlines()
        if "|" in line
    }
    missing = {
        name: path for name, path in discovered.items() if name not in EVENT_CATALOG
    }
    assert not missing, (
        "emitted names without an event_catalog.py row (add one, then run "
        f"python3 -m yoke_core.domain.event_catalog_render): {missing}"
    )


def test_expected_low_cadence_names_are_catalog_rows() -> None:
    assert sorted(set(EXPECTED_LOW_CADENCE) - set(EVENT_CATALOG)) == []


def test_hook_runner_telemetry_rows_carry_runner_metadata() -> None:
    for name, event_type, severity in HOOK_RUNNER_TELEMETRY_EVENTS:
        spec = EVENT_CATALOG[name]
        assert (spec.kind, spec.event_type, spec.owner_service, spec.severity) == (
            "system",
            event_type,
            "yoke_core.hooks",
            severity,
        )


def test_committed_catalog_doc_matches_the_code_catalog() -> None:
    committed = (_REPO_ROOT / EVENT_CATALOG_RELPATH).read_text(encoding="utf-8")
    assert committed == render_catalog_text(catalog_appendix(committed)), (
        "docs/event-catalog.md is stale; run "
        "python3 -m yoke_core.domain.event_catalog_render"
    )


def test_render_preserves_the_appendix_and_escapes_cell_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.event_catalog_render.assert_target_under_session_work_authority",
        lambda _path: None,
    )
    target = tmp_path / EVENT_CATALOG_RELPATH
    target.parent.mkdir(parents=True)
    target.write_text(f"old table\n{APPENDIX_SENTINEL}\n\n## Hand notes\n", encoding="utf-8", newline="\n")

    render_event_catalog(tmp_path)
    first = target.read_text(encoding="utf-8")
    render_event_catalog(tmp_path)

    assert target.read_text(encoding="utf-8") == first
    assert first.endswith(f"{APPENDIX_SENTINEL}\n\n## Hand notes\n")
    assert "old table" not in first
    assert "preflight\\|worktree" in first


def test_resolve_repo_root_strips_a_state_dir_yoke_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "data").mkdir(parents=True)
    monkeypatch.delenv("YOKE_REPO_ROOT", raising=False)
    monkeypatch.setenv("YOKE_ROOT", str(repo_root / "data"))

    assert resolve_repo_root() == repo_root.resolve()


def test_resolve_repo_root_keeps_a_worktree_yoke_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lane renders into its own tree, never into the owning main checkout."""
    worktree_root = tmp_path / "main" / ".worktrees" / "lane"
    worktree_root.mkdir(parents=True)
    monkeypatch.delenv("YOKE_REPO_ROOT", raising=False)
    monkeypatch.setenv("YOKE_ROOT", str(worktree_root))

    assert resolve_repo_root() == worktree_root.resolve()
