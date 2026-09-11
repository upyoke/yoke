"""Dispatch-path tests for ``yoke strategy doc archive|unarchive``."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _stub(result_by_function: dict):
    def _dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        _CAPTURED_REQUESTS.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result_by_function.get(request.function, {}),
        )

    return _dispatch


def _run(*argv: str) -> int:
    env = {"YOKE_SESSION_ID": "test-session"}
    with patch.dict("os.environ", env):
        with patch(
            "yoke_cli.commands._helpers.ensure_handlers_loaded",
        ):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                return cli_main(list(argv))


class TestDocArchive:
    def test_flips_then_renders_into_target_root(self, tmp_path: Path) -> None:
        results = {
            "strategy.doc.archive": {
                "project_id": 1,
                "project_slug": "yoke",
                "slug": "PAD",
                "archived": True,
                "changed": True,
            },
            "strategy.render.run": {
                "project_id": 1,
                "project_slug": "yoke",
                "docs": [
                    {
                        "slug": "PAD",
                        "updated_at": "x",
                        "file_text": "<!-- h -->\n# PAD\n",
                        "archived": True,
                    }
                ],
            },
        }
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub(results),
        ):
            rc = _run(
                "strategy",
                "doc",
                "archive",
                "PAD",
                "--target-root",
                str(tmp_path),
            )
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.archive",
            "strategy.render.run",
        ]
        assert (tmp_path / ".yoke" / "strategy" / "archive" / "PAD.md").read_text(
            encoding="utf-8"
        ) == "<!-- h -->\n# PAD\n"

    def test_skips_render_when_target_root_is_another_projects_checkout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
        monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
        from yoke_cli.config import machine_config
        import json

        other_checkout = tmp_path / "other-project-checkout"
        other_checkout.mkdir()
        config_path = machine_config.config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "projects": [
                        {"checkout": str(other_checkout), "project_id": 2},
                    ]
                }
            ),
            encoding="utf-8",
        )

        results = {
            "strategy.doc.archive": {
                "project_id": 1,
                "project_slug": "yoke",
                "slug": "PAD",
                "archived": True,
                "changed": True,
            },
        }
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub(results),
        ):
            rc = _run(
                "strategy",
                "doc",
                "archive",
                "PAD",
                "--target-root",
                str(other_checkout),
            )
        # The archive itself already landed in the DB, so the command
        # still succeeds; only the local render is skipped.
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.archive",
        ]
        assert not (other_checkout / ".yoke").exists()


class TestDocUnarchive:
    def test_flips_then_renders_into_target_root(self, tmp_path: Path) -> None:
        results = {
            "strategy.doc.unarchive": {
                "project_id": 1,
                "project_slug": "yoke",
                "slug": "PAD",
                "archived": False,
                "changed": True,
            },
            "strategy.render.run": {
                "project_id": 1,
                "project_slug": "yoke",
                "docs": [
                    {
                        "slug": "PAD",
                        "updated_at": "x",
                        "file_text": "<!-- h -->\n# PAD\n",
                        "archived": False,
                    }
                ],
            },
        }
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub(results),
        ):
            rc = _run(
                "strategy",
                "doc",
                "unarchive",
                "PAD",
                "--target-root",
                str(tmp_path),
            )
        assert rc == 0
        assert [r.function for r in _CAPTURED_REQUESTS] == [
            "strategy.doc.unarchive",
            "strategy.render.run",
        ]
        assert (tmp_path / ".yoke" / "strategy" / "PAD.md").read_text(
            encoding="utf-8"
        ) == "<!-- h -->\n# PAD\n"
