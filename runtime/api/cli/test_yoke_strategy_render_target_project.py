"""Project-aware ``target_root`` regression coverage for ``yoke strategy render``.

A ``--project platform`` render issued without ``--target-root`` from
the Yoke checkout must never overwrite Yoke's own rendered strategy
docs with Platform's. These tests exercise the fix end to end through
the CLI adapter rather than the resolver unit (covered by
``test_yoke_strategy_target_project.py``).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _stub(result: dict):
    def _dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result,
        )

    return _dispatch


def _run(*argv: str) -> int:
    env = {"YOKE_SESSION_ID": "test-session"}
    with patch.dict("os.environ", env):
        with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                return cli_main(list(argv))


def _register(config_path: Path, checkout: Path, project_id: int) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {"projects": [{"checkout": str(checkout), "project_id": project_id}]}
        ),
        encoding="utf-8",
    )


class TestRenderTargetRootMismatch:
    def test_explicit_destination_for_another_project_refuses(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
        monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
        from yoke_cli.config import machine_config

        yoke_checkout = tmp_path / "yoke-checkout"
        yoke_checkout.mkdir()
        (yoke_checkout / ".yoke" / "strategy").mkdir(parents=True)
        sentinel = yoke_checkout / ".yoke" / "strategy" / "MISSION.md"
        sentinel.write_text("original yoke content\n", encoding="utf-8")
        _register(machine_config.config_path(), yoke_checkout, 1)

        result = {
            "project_id": 2,
            "project_slug": "platform",
            "docs": [
                {
                    "slug": "MISSION",
                    "updated_at": "x",
                    "file_text": "<!-- h -->\n# Platform mission\n",
                }
            ],
        }
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub(result),
        ):
            rc = _run(
                "strategy",
                "render",
                "--project",
                "platform",
                "--target-root",
                str(yoke_checkout),
            )
        # Refused outright: nothing was fetched into the wrong checkout,
        # so Yoke's own rendered file is untouched.
        assert rc == 2
        assert sentinel.read_text(encoding="utf-8") == "original yoke content\n"

    def test_implicit_destination_prefers_projects_own_checkout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No --target-root / $YOKE_RENDER_TARGET_ROOT: Phase 1 resolves an
        # unrelated cwd fallback (stubbed here rather than depending on the
        # real repo root), and the project's own registered checkout must
        # win over it once the project is known.
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
        monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
        from yoke_cli.config import machine_config

        platform_checkout = tmp_path / "platform-checkout"
        platform_checkout.mkdir()
        _register(machine_config.config_path(), platform_checkout, 2)
        cwd_fallback = tmp_path / "cwd-fallback"
        cwd_fallback.mkdir()

        result = {
            "project_id": 2,
            "project_slug": "platform",
            "docs": [
                {
                    "slug": "MISSION",
                    "updated_at": "x",
                    "file_text": "<!-- h -->\n# Platform mission\n",
                }
            ],
        }
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub(result),
        ):
            with patch(
                "yoke_cli.commands.adapters.strategy_render."
                "resolve_target_root_for_cli",
                return_value=cwd_fallback,
            ):
                rc = _run("strategy", "render", "--project", "platform")
        assert rc == 0
        assert (platform_checkout / ".yoke" / "strategy" / "MISSION.md").read_text(
            encoding="utf-8"
        ) == "<!-- h -->\n# Platform mission\n"
        assert not (cwd_fallback / ".yoke").exists()
