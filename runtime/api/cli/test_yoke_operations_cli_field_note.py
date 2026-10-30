"""Feedback CLI dispatch and durable write coverage."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"echo": True, **({"yoke_version": request.payload.get("yoke_version"),
                "author": request.payload.get("agent"), "universe_fingerprint": "fixture@2026-01-01T00:00:00Z"}
                if request.function == "ouroboros.field_note.append" else {})},
    )


def _stub_call_dispatcher(**kwargs) -> FunctionCallResponse:
    request = FunctionCallRequest(
        function=kwargs["function_id"],
        actor=kwargs["actor"],
        target=kwargs["target"],
        payload=kwargs.get("payload") or {},
    )
    return _stub_ok(request)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run_capture(
    *argv: str,
    session_id: str | None = "test-session",
) -> tuple[int, str, str]:
    env = {}
    if session_id is not None:
        env["YOKE_SESSION_ID"] = session_id
    with patch.dict("os.environ", env, clear=session_id is None):
        with patch(
            "yoke_cli.transport.dispatcher._resolve_session_id",
            return_value=session_id,
        ):
            with patch(
                "yoke_cli.commands._helpers.call_dispatcher",
                side_effect=_stub_call_dispatcher,
            ):
                with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                    buf = io.StringIO()
                    err = io.StringIO()
                    with redirect_stdout(buf), redirect_stderr(err):
                        rc = cli_main(list(argv))
                    return rc, buf.getvalue(), err.getvalue()


def test_field_note_append_allows_direct_terminal_without_session() -> None:
    rc, _out, err = _run_capture(
        "feedback", "--to", "universe",
        "--category",
        "observation",
        "--evidence",
        "terminal field-note without harness session",
        session_id=None,
    )
    assert rc == 0, err
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ouroboros.field_note.append"
    assert req.actor.session_id == ""


def test_field_note_append_carries_external_checkout_project() -> None:
    """Registered external checkout → project hint on the append payload."""
    with patch(
        "yoke_cli.commands.adapters.feedback.client_project_context",
        return_value="42",
    ):
        rc, _out, err = _run_capture(
            "feedback", "--to", "universe",
            "--category",
            "failed",
            "--evidence",
            "platform recipe failed from its checkout",
        )
    assert rc == 0, err
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ouroboros.field_note.append"
    assert req.payload["project"] == "42"
    assert req.payload["category"] == "failed"


def test_field_note_append_carries_an_author_declared_target_project() -> None:
    """The fix's project is authored; the observing one stays automatic."""
    with patch(
        "yoke_cli.commands.adapters.feedback.client_project_context",
        return_value="yoke",
    ):
        rc, _out, err = _run_capture(
            "feedback", "--to", "universe",
            "--category",
            "failed",
            "--evidence",
            "a platform recipe failed, noticed from yoke",
            "--target-project",
            "platform",
        )
    assert rc == 0, err
    payload = _CAPTURED_REQUESTS[-1].payload
    assert payload["project"] == "yoke"
    assert payload["target_project"] == "platform"


def test_field_note_append_omits_target_project_when_not_declared() -> None:
    """Fast capture stays fast — the flag is never required or inferred."""
    with patch(
        "yoke_cli.commands.adapters.feedback.client_project_context",
        return_value="yoke",
    ):
        rc, _out, err = _run_capture(
            "feedback", "--to", "universe",
            "--category",
            "observation",
            "--evidence",
            "an author who cannot tell which repo owns the fix",
        )
    assert rc == 0, err
    assert "target_project" not in _CAPTURED_REQUESTS[-1].payload


def test_field_note_append_omits_project_from_unmapped_directory() -> None:
    """Unmapped cwd keeps global/no-checkout behavior — no project hint."""
    with patch(
        "yoke_cli.commands.adapters.feedback.client_project_context",
        return_value=None,
    ):
        rc, _out, err = _run_capture(
            "feedback", "--to", "universe",
            "--category",
            "observation",
            "--evidence",
            "note from an unmapped scratch directory",
        )
    assert rc == 0, err
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ouroboros.field_note.append"
    assert "project" not in req.payload


def test_field_note_subcommand_registered() -> None:
    # The top-level CLI catches argparse's help SystemExit and returns 0.
    # Capture stdout to verify HELP_BODY rendered.
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = cli_main(["feedback", "--to", "universe", "--help"])
    assert rc == 0
    out = buf.getvalue()
    from yoke_contracts.field_note_text import HELP_BODY

    assert HELP_BODY in out






def test_field_note_rejects_unknown_kind() -> None:
    rc, _out, err = _run_capture(
        "feedback", "--to", "universe",
        "--category",
        "compat-broken",
        "--evidence",
        "test",
    )
    assert rc != 0
    # argparse stderr names every choice the user could have passed.
    for kind in ("failed", "new", "unclear", "observation"):
        assert kind in err


def test_field_note_append_dispatches_against_project_id_schema(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.events import EmitResult
    from yoke_core.domain.handlers import ouroboros_field_note as _ofn
    from runtime.api.fixtures.file_test_db import init_test_db
    from runtime.api.fixtures.backlog import seed_fixture_operating_actor

    evidence = "observation: field-note command uses project_id schema"
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        monkeypatch.setenv("YOKE_SESSION_ID", "test-session")
        # The session stays unregistered (so the note carries no project
        # scope) and is written as the universe's recorded operating actor.
        with connect(db_path) as conn:
            seed_fixture_operating_actor(conn)
            conn.commit()
        # Keep the unmapped/no-checkout path: a live machine-config map
        # would otherwise send a project hint the bare test schema lacks.
        with (
            patch(
                "yoke_cli.commands.adapters.feedback."
                "client_project_context",
                return_value=None,
            ),
            patch.object(
                _ofn._events,
                "emit_event",
                return_value=EmitResult(
                    ok=True,
                    event_id="evt-feedback-cli",
                    reason="",
                    envelope=None,
                ),
            ),
        ):
            buf = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = cli_main(
                    [
                        "feedback", "--to", "universe",
                        "--category",
                        "observation",
                        "--evidence",
                        evidence,
                        "--json",
                    ]
                )

        assert rc == 0, err.getvalue()
        with connect(db_path) as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                "SELECT category, body, project_id FROM ouroboros_entries "
                f"WHERE body={p}",
                (evidence,),
            ).fetchone()
        assert row is not None
        assert row["category"] == "observation"
        assert row["project_id"] is None






@pytest.fixture(autouse=True)
def _feedback_identity(monkeypatch):
    monkeypatch.setattr("yoke_cli.feedback_reporter.feedback_provenance", lambda *_: {
        "yoke_version": "0.2.0.202610290013",
        "universe_fingerprint": "fixture@2026-01-01T00:00:00Z",
        "agent": "terminal", "reporter_email": None,
    })
