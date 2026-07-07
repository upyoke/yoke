"""Dispatch-path tests for ``yoke strategy doc replace``."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List, Optional
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


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(
    *argv: str,
    stdin_text: Optional[str] = None,
    session_id: str = "test-session",
) -> int:
    env = {"YOKE_SESSION_ID": session_id}
    with patch.dict("os.environ", env):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch(
                "yoke_cli.commands._helpers."
                "ensure_handlers_loaded"
            ):
                with patch("sys.stdin", io.StringIO(stdin_text or "")):
                    with redirect_stdout(io.StringIO()), \
                            redirect_stderr(io.StringIO()):
                        return cli_main(list(argv))


class TestDocReplace:
    def test_dispatches_with_stdin_content(self, tmp_path: Path) -> None:
        rc = _run(
            "strategy", "doc", "replace", "MISSION", "--stdin",
            "--base-updated-at", "2026-06-10T00:00:00Z",
            "--target-root", str(tmp_path),
            stdin_text="# Mission\n\nNew mission body.\n",
        )
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.replace", "strategy.render.run",
        ]
        req = _CAPTURED_REQUESTS[0]
        assert req.function == "strategy.doc.replace"
        assert req.target.kind == "global"
        assert req.payload == {
            "slug": "MISSION",
            "content": "# Mission\n\nNew mission body.\n",
            "base_updated_at": "2026-06-10T00:00:00Z",
            "force": False,
        }
        assert _CAPTURED_REQUESTS[1].payload == {}

    def test_dispatches_with_content_flag_and_force(
        self, tmp_path: Path,
    ) -> None:
        rc = _run(
            "strategy", "doc", "replace", "PAD",
            "--content", "# PAD\n", "--force",
            "--base-updated-at", "2026-06-10T00:00:00Z",
            "--target-root", str(tmp_path),
        )
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.replace", "strategy.render.run",
        ]
        req = _CAPTURED_REQUESTS[0]
        assert req.payload == {
            "slug": "PAD", "content": "# PAD\n",
            "base_updated_at": "2026-06-10T00:00:00Z", "force": True,
        }
        assert _CAPTURED_REQUESTS[1].payload == {}

    def test_dispatches_with_content_file(self, tmp_path: Path) -> None:
        content_file = tmp_path / "doc.md"
        content_file.write_text("# From file\n", encoding="utf-8")
        rc = _run(
            "strategy", "doc", "replace", "WISPS",
            "--content-file", str(content_file),
            "--base-updated-at", "2026-06-10T00:00:00Z",
            "--target-root", str(tmp_path),
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[0].payload["content"] == "# From file\n"
        assert _CAPTURED_REQUESTS[1].function == "strategy.render.run"

    def test_writes_full_render_after_success(
        self, tmp_path: Path, capsys,
    ) -> None:
        def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            result = {"old_bytes": 8, "new_bytes": 12}
            if request.function == "strategy.render.run":
                result = {
                    "project_id": 1,
                    "project_slug": "yoke",
                    "docs": [
                        {
                            "slug": "MISSION",
                            "updated_at": "x",
                            "file_text": "<!-- h -->\n# MISSION\n",
                        },
                        {
                            "slug": "PAD",
                            "updated_at": "y",
                            "file_text": "<!-- h -->\n# PAD\n",
                        },
                    ],
                }
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result=result,
            )

        env = {"YOKE_SESSION_ID": "test-session"}
        with patch.dict("os.environ", env):
            with patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch",
                side_effect=_stub,
            ):
                with patch(
                    "yoke_cli.commands._helpers."
                    "ensure_handlers_loaded"
                ):
                    rc = cli_main([
                        "strategy", "doc", "replace", "MISSION",
                        "--content", "# Mission\n",
                        "--base-updated-at", "2026-06-10T00:00:00Z",
                        "--target-root", str(tmp_path),
                    ])
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.replace", "strategy.render.run",
        ]
        assert _CAPTURED_REQUESTS[1].payload == {}
        assert (
            tmp_path / ".yoke" / "strategy" / "MISSION.md"
        ).read_text(encoding="utf-8") == "<!-- h -->\n# MISSION\n"
        assert (
            tmp_path / ".yoke" / "strategy" / "PAD.md"
        ).read_text(encoding="utf-8") == "<!-- h -->\n# PAD\n"
        out = capsys.readouterr().out
        assert "MISSION\twritten" in out
        assert "PAD\twritten" in out

    def test_unresolvable_anchor_skips_render_after_replace(self) -> None:
        # Anchor resolution is deferred to AFTER the replace lands: an
        # unresolvable anchor (e.g. a linked worktree without
        # --target-root) warns and skips the local render instead of
        # failing before the write. The replace dispatches and the
        # command still succeeds; the render does not dispatch.
        with patch(
            "yoke_cli.commands.adapters.strategy."
            "resolve_target_root_for_cli",
            side_effect=RuntimeError("no anchor"),
        ):
            rc = _run(
                "strategy", "doc", "replace", "MISSION",
                "--content", "# x\n",
                "--base-updated-at", "2026-06-10T00:00:00Z",
            )
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.replace",
        ]

    def test_missing_content_source_returns_two(self) -> None:
        rc = _run(
            "strategy", "doc", "replace", "MISSION",
            "--base-updated-at", "2026-06-10T00:00:00Z",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_base_updated_at_returns_two(self) -> None:
        rc = _run("strategy", "doc", "replace", "MISSION", "--content", "# x\n")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []
