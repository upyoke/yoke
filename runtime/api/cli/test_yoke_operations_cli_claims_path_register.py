"""CLI coverage for ``yoke claims path register --tentative-paths``."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"ok": True},
    )


def _run(*argv: str) -> tuple[int, str, str]:
    _CAPTURED.clear()
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ), patch(
            "yoke_cli.commands.adapters.claims.sync_local_snapshot_for_write"
        ), patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli_main(list(argv))
            return rc, out.getvalue(), err.getvalue()


def test_register_threads_tentative_paths() -> None:
    rc, _out, err = _run(
        "claims", "path", "register",
        "--item", "1819",
        "--paths", "runtime/api/domain/sure.py,runtime/api/domain/maybe.py",
        "--allow-planned",
        "--tentative-paths", "runtime/api/domain/maybe.py",
    )
    assert rc == 0, err
    payload = _CAPTURED[-1].payload
    assert payload["allow_planned"] is True
    assert payload["tentative_paths"] == ["runtime/api/domain/maybe.py"]


def test_register_rejects_tentative_paths_without_allow_planned() -> None:
    rc, _out, err = _run(
        "claims", "path", "register",
        "--item", "1819",
        "--paths", "runtime/api/domain/maybe.py",
        "--tentative-paths", "runtime/api/domain/maybe.py",
    )
    assert rc == 2
    assert "--tentative-paths requires --allow-planned" in err


def test_register_rejects_tentative_paths_outside_paths() -> None:
    rc, _out, err = _run(
        "claims", "path", "register",
        "--item", "1819",
        "--paths", "runtime/api/domain/sure.py",
        "--allow-planned",
        "--tentative-paths", "runtime/api/domain/other.py",
    )
    assert rc == 2
    assert "--tentative-paths must be a subset of --paths" in err
