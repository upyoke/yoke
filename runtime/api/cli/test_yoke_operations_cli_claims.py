"""Focused CLI tests for ``yoke claims work {acquire,release}`` — the
(epic_id, task_num) shape plus malformed-selector matrix conduct
fan-out depends on. Item-form dispatch lives in
``test_yoke_operations_cli_dispatch.py``.
"""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_claims_test_support import (
    _CAPTURED as _CAPTURED,
    _run as _run,
    _run_db as _run_db,
    _stub_ok as _stub_ok,
    claims_conn as claims_conn,
)


import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_cli.main import main as cli_main
from yoke_contracts.machine_config import paths


@pytest.fixture(autouse=True)
def _reset_captured(tmp_path, monkeypatch) -> None:
    _CAPTURED.clear()
    config = register_machine_checkout(tmp_path / "machine", tmp_path, 1)
    monkeypatch.setenv(paths.HOME_ENV, str(config.parent))
    monkeypatch.setenv(paths.CONFIG_FILE_ENV, str(config))
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# Acquire — epic_task target
# ---------------------------------------------------------------------------
class TestAcquireEpicTask:
    def test_acquire_epic_task_dispatches_typed_target(self) -> None:
        rc, _o, _e = _run(
            "claims",
            "work",
            "acquire",
            "--epic",
            "YOK-1872",
            "--task-num",
            "20",
            "--reason",
            "engineer dispatch",
        )
        assert rc == 0
        req = _CAPTURED[-1]
        assert req.function == "claims.work.acquire"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-1872" and req.target.task_num == 20
        assert req.payload["target"] == {
            "kind": "epic_task",
            "task_num": 20,
        }
        assert req.payload["reason"] == "engineer dispatch"

    def test_acquire_epic_task_without_reason_omits_reason(self) -> None:
        rc, *_ = _run(
            "claims",
            "work",
            "acquire",
            "--epic",
            "YOK-100",
            "--task-num",
            "1",
        )
        assert rc == 0
        assert "reason" not in _CAPTURED[-1].payload

    def test_acquire_epic_task_requires_both_selectors(self) -> None:
        # --epic without --task-num falls through to "no target" usage.
        rc, *_ = _run(
            "claims",
            "work",
            "acquire",
            "--epic",
            "YOK-1872",
            "--reason",
            "missing task-num",
        )
        assert rc == 2 and _CAPTURED == []

    def test_acquire_epic_task_rejects_invalid_public_ref(self) -> None:
        rc, *_ = _run(
            "claims",
            "work",
            "acquire",
            "--epic",
            "abc",
            "--task-num",
            "5",
            "--reason",
            "bad",
        )
        assert rc == 1 and _CAPTURED == []


# ---------------------------------------------------------------------------
# Release — epic_task selector
# ---------------------------------------------------------------------------
class TestReleaseEpicTask:
    """Relay contract: the adapter ships the typed epic_task target and
    the dispatcher's self_only verification resolves the session's own
    claim server-side (covered in
    runtime/api/domain/test_yoke_function_dispatch_claims.py)."""

    def test_release_epic_task_dispatches_typed_target(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--epic",
            "YOK-1872",
            "--task-num",
            "20",
            "--reason",
            "engineer return",
        )
        assert rc == 0, err
        req = _CAPTURED[-1]
        assert req.function == "claims.work.release"
        assert req.target.kind == "epic_task"
        assert req.target.public_ref == "YOK-1872" and req.target.task_num == 20
        assert req.target.claim_id is None
        assert req.payload == {"reason": "engineer return"}

    def test_release_item_dispatches_item_ref_target(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--item",
            "YOK-1872",
            "--reason",
            "done here",
        )
        assert rc == 0, err
        req = _CAPTURED[-1]
        assert req.function == "claims.work.release"
        assert req.target.kind == "item"
        assert req.target.public_ref == "YOK-1872"
        assert req.target.claim_id is None
        assert req.payload == {"reason": "done here"}

    def test_release_process_dispatches_process_payload(self) -> None:
        rc, _o, err = _run(
            "claims",
            "work",
            "release",
            "--process",
            "STRATEGIZE",
            "--project",
            "yoke",
            "--reason",
            "era closeout",
        )
        assert rc == 0, err
        req = _CAPTURED[-1]
        assert req.function == "claims.work.release"
        assert req.target.kind == "global"
        assert req.payload == {
            "reason": "era closeout",
            "process_key": "STRATEGIZE",
            "project": "yoke",
        }


# ---------------------------------------------------------------------------
# Help — selector form documented
# ---------------------------------------------------------------------------


class TestReleaseHelp:
    def test_help_lists_epic_task_selector(self) -> None:
        with (
            patch.dict("os.environ", {"YOKE_SESSION_ID": "sid"}),
            patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        ):
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                rc = cli_main(["claims", "work", "release", "--help"])
        assert rc == 0
        out = buf.getvalue()
        assert "--epic" in out
        assert "--task-num" in out
        assert "epic task" in out
        assert "--process" in out
        assert "STRATEGIZE" in out


class TestPathRegisterModes:
    def test_exception_mode_dispatches_without_paths(self) -> None:
        rc, _out, err = _run(
            "claims",
            "path",
            "register",
            "--item",
            "YOK-1872",
            "--mode",
            "exception",
            "--exception-reason",
            "evidence only",
        )
        assert rc == 0, err
        req = _CAPTURED[-1]
        assert req.function == "claims.path.register"
        assert req.target.public_ref == "YOK-1872"
        assert req.payload == {
            "paths": [],
            "mode": "exception",
            "allow_planned": False,
            "exception_reason": "evidence only",
        }

    @pytest.mark.parametrize(
        "extra, message",
        (
            ((), "--paths is required in exclusive mode"),
            (
                ("--mode", "exception"),
                "--exception-reason is required in exception mode",
            ),
            (
                (
                    "--mode",
                    "exception",
                    "--exception-reason",
                    "no files",
                    "--paths",
                    "runtime/api/foo.py",
                ),
                "--paths is not accepted in exception mode",
            ),
            (
                (
                    "--paths",
                    "runtime/api/foo.py",
                    "--exception-reason",
                    "wrong mode",
                ),
                "--exception-reason requires --mode exception",
            ),
        ),
    )
    def test_mode_specific_arguments_fail_closed(
        self,
        extra: tuple[str, ...],
        message: str,
    ) -> None:
        rc, _out, err = _run(
            "claims",
            "path",
            "register",
            "--item",
            "YOK-1872",
            *extra,
        )
        assert rc == 2
        assert message in err
        assert _CAPTURED == []
