"""Pre-dispatch project-mismatch regression for ``yoke strategy ingest``.

A known mismatched target_root must refuse before ``read_ingest_files``
and before any mutating dispatch: zero ``strategy.ingest.run`` calls,
zero DB writes. Content-file handoffs are unaffected (covered in
``test_yoke_strategy_ingest_content_file.py``) since they never read
from target_root.
"""

from __future__ import annotations

import io
import json
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
            success=True, function=request.function, version=request.version,
            request_id=request.request_id,
            result=result_by_function.get(request.function, {}),
        )

    return _dispatch


def test_known_mismatched_checkout_refuses_before_any_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    from yoke_cli.config import machine_config

    other_checkout = tmp_path / "other-project-checkout"
    other_checkout.mkdir()
    config_path = machine_config.config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {"projects": [{"checkout": str(other_checkout), "project_id": 2}]}
        ),
        encoding="utf-8",
    )
    # A rendered file exists at the mismatched checkout; if the guard
    # were skipped, read_ingest_files would happily pick it up and ship
    # it to the resolved project's DB row.
    docs_dir = other_checkout / ".yoke" / "strategy"
    docs_dir.mkdir(parents=True)
    (docs_dir / "MISSION.md").write_text(
        "<!-- h -->\n# Wrong-project content\n", encoding="utf-8",
    )

    results = {"strategy.doc.list": {"project_id": 1, "project_slug": "yoke"}}
    env = {"YOKE_SESSION_ID": "test-session"}
    with patch.dict("os.environ", env):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub(results),
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    rc = cli_main([
                        "strategy", "ingest", "MISSION",
                        "--target-root", str(other_checkout),
                    ])

    assert rc == 2
    # Only the identity read happened — zero strategy.ingest.run calls,
    # so zero DB writes.
    assert [r.function for r in _CAPTURED_REQUESTS] == ["strategy.doc.list"]
