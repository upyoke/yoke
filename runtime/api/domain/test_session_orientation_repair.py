"""A session that misses its orientation block gets it on the next event.

Orientation is composed in one short-lived hook process and printed for the
harness to read, and the block can still be lost between those two moments:
a deny prints its own message in place of the merged allow stdout, and a
hook the harness kills on its own timeout prints nothing at all. A live
Cursor session hit exactly that during a relay-turbulence window and then
ran its whole life un-oriented, because the composer had already recorded
the session as oriented.

These regressions pin the repair: delivery — not composition — is what
retires a session's orientation, an un-delivered block returns on the next
context-bearing event for that harness, the repeat says so where both the
operator and the agent can see it, and a session that was oriented cleanly
never gets a second copy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.hook_runner.chain_registry import (
    session_orientation_event,
    session_orientation_redelivery_event,
)
from yoke_core.domain import session_orientation as so
from yoke_core.domain import session_orientation_delivery as delivery
from yoke_core.domain.project_scratch_roots import ENV_KEY as SCRATCH_ROOT_ENV_KEY


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A minimal managed project: the .yoke dir the installer always makes."""
    (tmp_path / ".yoke").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def isolated_markers(tmp_path_factory, monkeypatch) -> None:
    """Point the attempt/delivery markers at a per-test scratch root."""
    monkeypatch.setenv(
        SCRATCH_ROOT_ENV_KEY,
        str(tmp_path_factory.mktemp("markers")),
    )
    monkeypatch.setattr(delivery, "_composed_session", None)


def _payload(root: Path, session_id: str = "sess-abc") -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "cwd": str(root),
            "hook_event_name": "UserPromptSubmit",
        }
    )


def _cursor_payload(
    root: Path,
    session_id: str = "sess-cursor",
    event: str = "sessionStart",
) -> str:
    return json.dumps(
        {
            "hook_event_name": event,
            "session_id": session_id,
            "conversation_id": session_id,
            "workspace_roots": [str(root)],
        }
    )


def test_a_lost_block_comes_back_on_the_next_prompt(project: Path) -> None:
    # The composing process never confirmed delivery, so as far as the
    # session is concerned the block never arrived — and the next prompt is
    # the first chance to say so.
    lost = so.orientation_for_hook("UserPromptSubmit", _payload(project))
    repeat = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert lost is not None
    assert repeat is not None
    assert so.ORIENTATION_HEADING in repeat
    assert "Your Session: sess-abc" in repeat


def test_the_repeat_lands_exactly_once(project: Path) -> None:
    so.orientation_for_hook("UserPromptSubmit", _payload(project))
    repeat = so.orientation_for_hook("UserPromptSubmit", _payload(project))
    so.confirm_orientation_delivery()
    third = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert repeat is not None
    assert third is None


def test_a_delivered_block_is_never_sent_twice(project: Path) -> None:
    first = so.orientation_for_hook("UserPromptSubmit", _payload(project))
    so.confirm_orientation_delivery()
    second = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert first is not None
    assert "NOTE:" not in first
    assert second is None


def test_the_miss_is_visible_to_the_operator_and_the_agent(
    project: Path,
    capsys,
) -> None:
    # A session that started without its bearings is otherwise invisible:
    # the block simply never appeared and nothing later says so.
    so.orientation_for_hook("UserPromptSubmit", _payload(project))
    capsys.readouterr()
    repeat = so.orientation_for_hook("UserPromptSubmit", _payload(project))

    assert repeat is not None
    assert repeat.startswith("NOTE: this session's startup orientation")
    err = capsys.readouterr().err
    assert so.ORIENTATION_REDELIVERED_MARKER in err
    assert "sess-abc" in err


def test_confirming_delivery_needs_the_composing_process(project: Path) -> None:
    # Confirmation carries no session argument on purpose: it is the
    # composing process reporting on itself, and a process that composed
    # nothing must not retire someone else's pending orientation.
    so.confirm_orientation_delivery()

    assert not delivery.orientation_delivered("sess-abc")
    assert so.orientation_for_hook("UserPromptSubmit", _payload(project)) is not None


def test_cursor_repairs_on_its_tool_result_event(project: Path) -> None:
    # Cursor's prompt hook answers block/allow only, so the tool-result
    # event is the session's one repeating injection channel.
    lost = so.orientation_for_hook(
        "SessionStart",
        _cursor_payload(project),
        cursor=True,
    )
    repeat = so.orientation_for_hook(
        "PostToolUse",
        _cursor_payload(project, event="afterShellExecution"),
        cursor=True,
    )

    assert lost is not None
    assert repeat is not None
    assert "Your Session: sess-cursor" in repeat


def test_cursor_stays_silent_once_its_startup_block_landed(project: Path) -> None:
    so.orientation_for_hook("SessionStart", _cursor_payload(project), cursor=True)
    so.confirm_orientation_delivery()
    repeat = so.orientation_for_hook(
        "PostToolUse",
        _cursor_payload(project, event="afterShellExecution"),
        cursor=True,
    )

    assert repeat is None


def test_cursor_prompt_submit_is_never_the_repair_channel(project: Path) -> None:
    so.orientation_for_hook("SessionStart", _cursor_payload(project), cursor=True)

    assert (
        so.orientation_for_hook(
            "UserPromptSubmit",
            _cursor_payload(project, event="beforeSubmitPrompt"),
            cursor=True,
        )
        is None
    )


@pytest.mark.parametrize("cursor", [False, True])
def test_every_harness_has_a_repeating_repair_channel(cursor: bool) -> None:
    # A repair event that fires once per session cannot repair anything:
    # Claude and Codex reuse their per-prompt channel, Cursor moves to the
    # tool-result event its prompt hook cannot serve.
    startup = session_orientation_event(cursor=cursor)
    repair = session_orientation_redelivery_event(cursor=cursor)

    assert repair == ("PostToolUse" if cursor else startup)
