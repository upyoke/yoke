"""The spool hand-off between Cursor's streaming event and the next hook.

The streaming event's hook is shell, and the reader is Python, so these
exercise the real rendered shell command rather than a Python stand-in for
it — a quoting or path mistake in that string is exactly the failure this
hand-off is exposed to, and no amount of testing the reader alone finds it.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_core.domain.agents_render_hooks import render_cursor_hooks_block
from yoke_harness.hooks import cursor_model_spool

SESSION = "3f2b1c88-0000-4000-8000-abcdefabcdef"
OTHER_SESSION = "99999999-0000-4000-8000-abcdefabcdef"


@pytest.fixture
def spool_home(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    return tmp_path


def _fire_capture_hook(payload: dict, home) -> int:
    """Run the rendered hook exactly as Cursor runs it."""
    command = render_cursor_hooks_block()["hooks"]["afterAgentThought"][0]["command"]
    completed = subprocess.run(
        command,
        shell=True,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"HOME": str(home), "YOKE_MACHINE_HOME": str(home), "PATH": "/bin:/usr/bin"},
    )
    assert completed.stdout.strip() == "{}", completed
    return completed.returncode


def test_rendered_shell_hook_spools_where_the_reader_looks(spool_home) -> None:
    payload = {
        "hook_event_name": "afterAgentThought",
        "session_id": SESSION,
        "model": "cursor-grok-4.5-high",
        "model_id": "grok-4.5",
    }
    assert _fire_capture_hook(payload, spool_home) == 0
    assert cursor_model_spool.drain_model(SESSION) == "grok-4.5"


def test_draining_consumes_the_entry(spool_home) -> None:
    """A spooled payload is a one-shot hand-off. Leaving it behind would
    re-ship the same model on every later hook for the rest of the session."""
    _fire_capture_hook({"session_id": SESSION, "model_id": "grok-4.5"}, spool_home)
    assert cursor_model_spool.drain_model(SESSION) == "grok-4.5"
    assert cursor_model_spool.drain_model(SESSION) is None


def test_concurrent_fires_do_not_interleave(spool_home) -> None:
    """The streaming event fires many times per turn — 17 in one measured
    two-token reply — so each fire gets its own file."""
    for _ in range(5):
        _fire_capture_hook({"session_id": SESSION, "model_id": "grok-4.5"}, spool_home)
    files = sorted(cursor_model_spool.spool_dir().iterdir())
    assert len(files) == 5, files
    for entry in files:
        assert json.loads(entry.read_text())["model_id"] == "grok-4.5"


def test_another_session_entry_is_left_for_its_own_hook(spool_home) -> None:
    _fire_capture_hook({"session_id": OTHER_SESSION, "model_id": "other"}, spool_home)
    assert cursor_model_spool.drain_model(SESSION) is None
    assert cursor_model_spool.drain_model(OTHER_SESSION) == "other"


def test_missing_spool_is_not_an_error(spool_home) -> None:
    """Every session before the first fire is this case, and a hook must
    never fail on a bookkeeping file."""
    assert cursor_model_spool.drain_model(SESSION) is None


def test_unparseable_entry_is_skipped(spool_home) -> None:
    spool = cursor_model_spool.spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    (spool / "truncated.json").write_text('{"session_id": "3f2b')
    _fire_capture_hook({"session_id": SESSION, "model_id": "grok-4.5"}, spool_home)
    assert cursor_model_spool.drain_model(SESSION) == "grok-4.5"
