"""What each surface records when no session identity resolves.

Three surfaces used to mint ``<epoch>-<pid>`` when the chain came back
empty. The value looked like a session id, joined to no
``harness_sessions`` row, and made "no identity" indistinguishable from
a real one in the event log. Each now declares an outcome instead, and
those outcomes are pinned here so a future edit has to change a test to
reintroduce an invented id.

* generic event telemetry records the empty string every other domain
  emitter records (also exercised end-to-end in
  ``test_emit_event_sections``);
* the epic-task cascade records the same empty string;
* the fail-open Stop hook records the ``"unknown"`` sentinel the hook
  helpers already resolve to, because it must still run its auto-commit.
"""

from __future__ import annotations

import ast
from typing import List
from unittest.mock import patch

import pytest

from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_core.domain import agent_stop, emit_event, epic_cascade
from runtime.api.domain.test_session_env_chain_ownership import (
    REPO_ROOT,
    source_files,
)


@pytest.fixture()
def no_ambient_session(monkeypatch):
    """No env chain, and a machine home holding no anchor or mapping."""
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_event_emitter_records_the_empty_session(no_ambient_session):
    assert emit_event._resolve_session_id(None) == ""


def test_event_emitter_still_honours_an_explicit_session(no_ambient_session):
    assert emit_event._resolve_session_id("explicit") == "explicit"


def test_cascade_records_the_empty_session(no_ambient_session):
    assert epic_cascade._resolve_session_id() == ""


def test_stop_hook_records_the_unknown_sentinel(tmp_path, monkeypatch):
    db_path = tmp_path / "yoke.db"
    db_path.write_text("seed\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    with patch(
        "yoke_core.hooks.helpers.find_project_root", return_value=str(tmp_path),
    ), patch(
        "yoke_core.hooks.helpers.resolve_yoke_db", return_value=str(db_path),
    ), patch(
        "yoke_core.hooks.helpers.get_session_id", return_value="unknown",
    ), patch(
        "yoke_core.domain.agent_stop._read_session_id_from_hook_stdin",
        return_value="",
    ), patch(
        "yoke_core.domain.agent_stop.process_dispatch_chains",
    ) as chains, patch(
        "yoke_core.domain.agent_stop.emit_harness_session_stopped",
    ):
        agent_stop.run_hook()

    assert chains.call_args.kwargs["session_id"] == "unknown"


def _mints_a_session_id(tree: ast.AST) -> List[int]:
    """Line numbers of f-strings shaped like ``<clock>-<pid>``.

    Matches the minting shape rather than any particular clock call, so
    ``time.time()``, ``os.times()``, and whatever comes next all count.
    """
    found: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        rendered = "".join(
            part.value if isinstance(part, ast.Constant) else "\0"
            for part in node.values
        )
        if rendered != "\0-\0":
            continue
        if "getpid" in ast.dump(node):
            found.append(node.lineno)
    return found


def test_no_live_module_mints_a_session_id() -> None:
    offenders: List[str] = []
    for path in source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - defensive
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        offenders.extend(
            f"{rel}:{lineno}" for lineno in _mints_a_session_id(tree)
        )

    assert not offenders, (
        "a synthesised clock-and-pid id is indistinguishable from a real "
        "session id and matches no harness_sessions row; declare what the "
        "surface records when identity is missing instead:\n  "
        + "\n  ".join(offenders)
    )
