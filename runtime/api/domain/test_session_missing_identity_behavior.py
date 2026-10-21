"""What each surface records when no session identity resolves.

Two surfaces used to mint ``<epoch>-<pid>`` when the chain came back
empty. The value looked like a session id, joined to no
``harness_sessions`` row, and made "no identity" indistinguishable from
a real one in the event log. Each now declares an outcome instead, and
those outcomes are pinned here so a future edit has to change a test to
reintroduce an invented id.

* generic event telemetry records the empty string every other domain
  emitter records (also exercised end-to-end in
  ``test_emit_event_sections``);
* the epic-task cascade records the same empty string.
"""

from __future__ import annotations

import ast
from typing import List

import pytest

from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_core.domain import emit_event, epic_cascade
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
