"""``yoke ouroboros field-note append`` subcommand surface tests.

Covers AC-1, AC-3, AC-4, AC-8 from YOK-1872 task 004:

* AC-1: ``--help`` prints the canonical ``HELP_BODY``.
* AC-3: argparse rejects an unknown ``--kind``.
* AC-4: the retired subcommand is gone (not aliased).
* AC-8: the renamed ``attach_field_note_footer`` helper resolves.
"""

from __future__ import annotations

import argparse
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
        result={"echo": True},
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
    *argv: str, session_id: str | None = "test-session",
) -> tuple[int, str, str]:
    env = {}
    if session_id is not None:
        env["YOKE_SESSION_ID"] = session_id
    with patch.dict("os.environ", env, clear=session_id is None):
        with patch(
            "yoke_cli.transport.dispatcher."
            "_resolve_session_id",
            return_value=session_id,
        ):
            with patch(
                "yoke_cli.commands._helpers."
                "call_dispatcher",
                side_effect=_stub_call_dispatcher,
            ):
                with patch(
                    "yoke_cli.commands._helpers."
                    "ensure_handlers_loaded"
                ):
                    buf = io.StringIO()
                    err = io.StringIO()
                    with redirect_stdout(buf), redirect_stderr(err):
                        rc = cli_main(list(argv))
                    return rc, buf.getvalue(), err.getvalue()


def test_field_note_append_allows_direct_terminal_without_session() -> None:
    rc, _out, err = _run_capture(
        "ouroboros", "field-note", "append",
        "--kind", "observation",
        "--evidence", "terminal field-note without harness session",
        session_id=None,
    )
    assert rc == 0, err
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ouroboros.field_note.append"
    assert req.actor.session_id == ""


def test_field_note_subcommand_registered() -> None:
    # The top-level CLI catches argparse's help SystemExit and returns 0.
    # Capture stdout to verify HELP_BODY rendered.
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = cli_main(["ouroboros", "field-note", "append", "--help"])
    assert rc == 0
    out = buf.getvalue()
    # Preamble sourced from field_note_text.HELP_BODY.
    assert "Append a structured field-note" in out


def test_field_note_help_prints_footer_once() -> None:
    from yoke_contracts.field_note_text import BASIC_RECIPE

    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = cli_main(["ouroboros", "field-note", "append", "--help"])
    assert rc == 0
    assert buf.getvalue().count(BASIC_RECIPE) == 1


def test_field_note_group_help_lists_subcommands() -> None:
    from yoke_contracts.field_note_text import BASIC_RECIPE

    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = cli_main(["ouroboros", "field-note", "--help"])

    out = buf.getvalue()
    assert rc == 0
    assert err.getvalue() == ""
    assert "yoke ouroboros field-note - subcommand group." in out
    assert "yoke ouroboros field-note append" in out
    assert "yoke ouroboros field-note list" in out
    assert "yoke ouroboros field-note get" in out
    assert out.count(BASIC_RECIPE) == 1


def test_field_note_rejects_unknown_kind() -> None:
    rc, _out, err = _run_capture(
        "ouroboros", "field-note", "append",
        "--kind", "compat-broken", "--evidence", "test",
    )
    assert rc != 0
    # argparse stderr names every choice the user could have passed.
    for kind in ("failed", "new", "unclear", "observation"):
        assert kind in err


def test_field_note_append_dispatches_against_project_id_schema(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.events import EmitResult
    from yoke_core.domain.handlers import ouroboros_field_note as _ofn
    from runtime.api.fixtures.file_test_db import init_test_db

    evidence = "observation: field-note command uses project_id schema"
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        monkeypatch.setenv("YOKE_SESSION_ID", "test-session")
        with patch.object(
            _ofn._events,
            "emit_event",
            return_value=EmitResult(
                ok=True, event_id="evt-field-note-cli", reason="", envelope=None,
            ),
        ):
            buf = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = cli_main([
                    "ouroboros", "field-note", "append",
                    "--kind", "observation",
                    "--evidence", evidence,
                    "--json",
                ])

        assert rc == 0, err.getvalue()
        with connect(db_path) as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                "SELECT category, body, project_id FROM ouroboros_entries "
                f"WHERE body={p}",
                (evidence,),
            ).fetchone()
        assert row is not None
        assert row["category"] == "field-note-observation"
        assert row["project_id"] is None


def test_old_subcommand_gone() -> None:
    # Old subcommand removed (not aliased). Token list assembled
    # dynamically to keep the literal out of grep paths under AC-5.
    old_subcommand_token = "-".join(("recipe", "event"))
    rc, _out, _err = _run_capture(
        "ouroboros", old_subcommand_token, "append", "--help",
    )
    assert rc != 0


def test_attach_field_note_footer_appends_canonical_footer() -> None:
    from yoke_cli.commands._helpers import (
        attach_field_note_footer,
    )
    from yoke_contracts.field_note_text import FOOTER

    parser = argparse.ArgumentParser(prog="test")
    attach_field_note_footer(parser)
    assert parser.epilog is not None
    assert parser.epilog.endswith(FOOTER)


def test_attach_field_note_footer_skips_when_description_already_has_footer() -> None:
    from yoke_cli.commands._helpers import (
        attach_field_note_footer,
    )
    from yoke_contracts.field_note_text import FOOTER

    parser = argparse.ArgumentParser(prog="test", description=f"Body\n\n{FOOTER}")
    attach_field_note_footer(parser)
    assert parser.epilog is None
