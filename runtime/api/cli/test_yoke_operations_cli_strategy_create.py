"""Dispatch-path tests for ``yoke strategy doc create``."""

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


class TestDocCreate:
    def test_dispatches_with_content_file(self, tmp_path: Path) -> None:
        content_file = tmp_path / "OPERATIONS-NOTES.md"
        content_file.write_text("# OPERATIONS NOTES\n\nBody.\n", encoding="utf-8")

        rc = _run(
            "strategy", "doc", "create", "OPERATIONS-NOTES",
            "--content-file", str(content_file),
            "--target-root", str(tmp_path),
        )

        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.create", "strategy.render.run",
        ]
        req = _CAPTURED_REQUESTS[0]
        assert req.target.kind == "global"
        assert req.payload == {
            "slug": "OPERATIONS-NOTES",
            "content": "# OPERATIONS NOTES\n\nBody.\n",
        }
        assert _CAPTURED_REQUESTS[1].payload == {}

    def test_dispatches_with_stdin(self, tmp_path: Path) -> None:
        rc = _run(
            "strategy", "doc", "create", "OPERATIONS-NOTES",
            "--stdin",
            "--target-root", str(tmp_path),
            stdin_text="# From stdin\n",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[0].payload["content"] == "# From stdin\n"

    def test_writes_full_render_after_success(
        self, tmp_path: Path, capsys,
    ) -> None:
        def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            result = {"slug": "OPERATIONS-NOTES", "new_bytes": 18}
            if request.function == "strategy.render.run":
                result = {
                    "project_id": 1,
                    "project_slug": "yoke",
                    "docs": [
                        {
                            "slug": "OPERATIONS-NOTES",
                            "updated_at": "x",
                            "file_text": "<!-- h -->\n# OPERATIONS NOTES\n",
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
                        "strategy", "doc", "create", "OPERATIONS-NOTES",
                        "--content", "# Operations\n",
                        "--target-root", str(tmp_path),
                    ])
        assert rc == 0
        rendered = tmp_path / ".yoke" / "strategy" / "OPERATIONS-NOTES.md"
        assert rendered.read_text(encoding="utf-8") == (
            "<!-- h -->\n# OPERATIONS NOTES\n"
        )
        assert "OPERATIONS-NOTES\twritten" in capsys.readouterr().out

    def test_unresolvable_anchor_skips_render_after_create(self) -> None:
        with patch(
            "yoke_cli.commands.adapters.strategy_create."
            "resolve_target_root_for_cli",
            side_effect=RuntimeError("no anchor"),
        ):
            rc = _run(
                "strategy", "doc", "create", "OPERATIONS-NOTES",
                "--content", "# Operations\n",
            )
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.create",
        ]

    def test_missing_content_source_returns_two(self) -> None:
        rc = _run("strategy", "doc", "create", "OPERATIONS-NOTES")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []
