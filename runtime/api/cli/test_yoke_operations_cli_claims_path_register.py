"""CLI coverage for ``yoke claims path register`` argument refusals."""

from __future__ import annotations

import io
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

from yoke_cli.commands.adapters.claims_path_unmaterialized import (
    unmaterialized_paths,
)
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


# The registry is built from committed tree state, so a path that exists
# nowhere yet can only be refused. Answering that at the server costs a
# whole-tree scan plus a relay round trip; the reported symptom was a
# command that printed nothing for minutes and created no claim.
_SELF = "runtime/api/cli/test_yoke_operations_cli_claims_path_register.py"


def test_register_refuses_a_path_that_exists_nowhere_yet() -> None:
    rc, _out, err = _run(
        "claims", "path", "register",
        "--item", "1819",
        "--paths", f"{_SELF},runtime/api/domain/not_created_yet.py",
    )

    assert rc == 2
    assert "runtime/api/domain/not_created_yet.py" in err
    assert _SELF not in err
    assert "--allow-planned" in err
    assert _CAPTURED == []


def test_register_accepts_a_committed_path_without_allow_planned() -> None:
    rc, _out, err = _run(
        "claims", "path", "register", "--item", "1819", "--paths", _SELF,
    )

    assert rc == 0, err
    assert _CAPTURED[-1].payload["paths"] == [_SELF]


def test_a_planned_path_is_claimable_when_the_operator_says_so() -> None:
    rc, _out, err = _run(
        "claims", "path", "register",
        "--item", "1819",
        "--paths", "runtime/api/domain/not_created_yet.py",
        "--allow-planned",
    )

    assert rc == 0, err
    assert _CAPTURED[-1].payload["allow_planned"] is True


def test_an_untracked_file_on_disk_is_not_called_unmaterialized(tmp_path) -> None:
    # It may be uncommitted, but the operator created it and the server may
    # well have a row for it. The cheap probe never decides that case; only
    # a path present in neither tree is refused here.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "scratch.txt").write_text("", encoding="utf-8")

    assert unmaterialized_paths(["scratch.txt"], repo_root=tmp_path) == []
    assert unmaterialized_paths(["absent.txt"], repo_root=tmp_path) == ["absent.txt"]


def test_a_probe_that_cannot_run_refuses_nothing(tmp_path) -> None:
    assert unmaterialized_paths(["anything.py"], repo_root=tmp_path / "absent") == []
