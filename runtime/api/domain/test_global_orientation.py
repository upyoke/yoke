"""Startup orientation for a session opened outside every Yoke project.

The block says Yoke is installed, names this folder as outside every project
and teaches one next action — the user-level ``yoke-global`` skill. Project
folders on this machine are optional context that gives way first so the
required lines always fit the smallest harness inline channel.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_core.domain import global_orientation as go
from yoke_core.domain import session_orientation as so
from yoke_core.domain import session_orientation_delivery as delivery
from yoke_core.domain.project_scratch_roots import ENV_KEY as SCRATCH_ROOT_ENV_KEY

BUDGET = min(INLINE_CONTEXT_BYTES.values())
_REAL_PROJECT_FOLDERS = go._project_folders


@pytest.fixture(autouse=True)
def isolated(tmp_path_factory, monkeypatch) -> None:
    monkeypatch.setenv(SCRATCH_ROOT_ENV_KEY, str(tmp_path_factory.mktemp("markers")))
    monkeypatch.setattr(delivery, "_composed_session", None)
    monkeypatch.setattr(go, "_project_folders", lambda: [])


def test_block_teaches_scope_and_one_next_action(tmp_path: Path) -> None:
    out = go.render_global_orientation("sess-g", tmp_path)

    assert out.startswith(so.ORIENTATION_HEADING)
    assert "Your Session: sess-g" in out
    assert f"outside every Yoke project: {tmp_path}" in out
    assert "use the `yoke-global` skill to pick or add its project" in out
    assert "`yoke status`" in out and go.DOCS_URL in out
    assert "Project folders" not in out
    assert "Writing to the user: Each message to the user" in out
    assert len(out.encode("utf-8")) <= BUDGET


def test_no_session_id_renders_nothing(tmp_path: Path) -> None:
    assert go.render_global_orientation("", tmp_path) == ""
    assert go.render_global_orientation("unknown", tmp_path) == ""


def test_project_folders_are_listed_and_summarized(tmp_path, monkeypatch) -> None:
    folders = [f"/work/project-{n}" for n in range(7)]
    monkeypatch.setattr(go, "_project_folders", lambda: folders)

    out = go.render_global_orientation("sess-g", tmp_path)

    assert "Project folders on this machine:" in out
    assert "- /work/project-4" in out and "- /work/project-5" not in out
    assert "- and 2 more: `yoke projects list`" in out


def test_optional_folders_give_way_to_the_budget(tmp_path, monkeypatch) -> None:
    folders = [f"/work/{'x' * 900}-{n}" for n in range(5)]
    monkeypatch.setattr(go, "_project_folders", lambda: folders)

    out = go.render_global_orientation("sess-g", tmp_path)

    assert len(out.encode("utf-8")) <= BUDGET
    assert "`yoke-global`" in out


def test_unreadable_machine_config_omits_folders(monkeypatch) -> None:
    from yoke_contracts.machine_config import runtime

    def broken(*_a, **_k):
        raise ValueError("unreadable")

    monkeypatch.setattr(runtime, "load_config", broken)
    assert _REAL_PROJECT_FOLDERS() == []


@pytest.mark.parametrize("cursor", [False, True])
def test_hook_entry_orients_outside_a_project_once(
    tmp_path: Path, cursor, monkeypatch
) -> None:
    # A real hook process runs in the session's folder, outside every project,
    # so its delivery markers resolve in machine scope.
    monkeypatch.chdir(tmp_path)
    if cursor:
        event = "sessionStart"
        payload = {
            "hook_event_name": event,
            "session_id": "sess-c",
            "conversation_id": "sess-c",
            "workspace_roots": [str(tmp_path)],
        }
    else:
        event = "UserPromptSubmit"
        payload = {
            "session_id": "sess-c",
            "cwd": str(tmp_path),
            "hook_event_name": event,
        }
    stdin = json.dumps(payload)
    event_name = "SessionStart" if cursor else event

    out = so.orientation_for_hook(event_name, stdin, cursor=cursor)

    assert out is not None and "`yoke-global`" in out
    delivery.confirm_orientation_delivery(out)
    assert so.orientation_for_hook(event_name, stdin, cursor=cursor) is None
