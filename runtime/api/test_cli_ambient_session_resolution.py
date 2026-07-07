"""Regression: the CLI transport resolves the ambient harness session via
the hook-written process-anchor ancestry, not just the env chain.

On the https transport the client is the only place the caller's session
can be stamped into the request -- the remote server cannot inspect the
client's process tree. An env-only resolver dropped the ancestry fallback
and denied every mutating CLI call from a harness that does not export a
session env var (e.g. Claude Desktop, which relies on the anchor registry).

Sibling of ``test_service_client_structured_api_adapter.py`` (at the
350-line cap); ``build_actor`` is re-exported from there but lives in
``yoke_cli.transport.dispatcher``.
"""

from __future__ import annotations

import pytest

from yoke_cli.config import machine_config
from yoke_cli.transport.dispatcher import build_actor
from yoke_contracts import session_identity


def _clear_session_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("YOKE_ACTOR_ID", raising=False)


def test_build_actor_resolves_via_process_anchor_when_env_empty(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_session_env(monkeypatch)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    anchors_dir = machine_config.yoke_home() / session_identity.ANCHORS_DIR_NAME
    session_identity.record_session_anchor(
        "sess-anchored",
        anchors_dir,
        anchor=session_identity.ProcessAnchor(
            pid=5151, start_time="s-5151", process_name="claude",
        ),
    )
    monkeypatch.setattr(
        session_identity, "ancestor_pids",
        lambda _pid=None, parents=None: [5151],
    )
    monkeypatch.setattr(
        session_identity, "process_start_time", lambda _pid: "s-5151",
    )
    assert build_actor().session_id == "sess-anchored"


def test_build_actor_empty_when_no_env_and_no_anchor(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_session_env(monkeypatch)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "empty-home"))
    assert build_actor().session_id == ""
