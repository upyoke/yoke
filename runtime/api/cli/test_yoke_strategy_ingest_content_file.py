"""CLI coverage for strategy ingest handoff files."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters import strategy_render
from yoke_contracts.api.function_call import FunctionCallResponse


def _response() -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="strategy.ingest.run",
        version="v1",
        request_id="content-file-test",
        result={"docs": []},
    )


def test_lane_handoff_content_file_is_shipped_for_one_slug(
    tmp_path: Path,
) -> None:
    handoff = tmp_path / "FLEET-COMMS.md"
    rendered = "<!-- rendered header -->\n# Fleet communications\n"
    handoff.write_text(rendered, encoding="utf-8")

    with patch.object(strategy_render._helpers, "ensure_handlers_loaded"), \
            patch.object(strategy_render, "build_actor", return_value=object()), \
            patch.object(strategy_render, "strategy_target", return_value=object()), \
            patch.object(
                strategy_render,
                "resolve_target_root_for_cli",
                return_value=tmp_path,
            ), \
            patch.object(
                strategy_render, "call_dispatcher", return_value=_response(),
            ) as dispatch:
        rc = strategy_render.strategy_ingest([
            "FLEET-COMMS", "--content-file", str(handoff), "--json",
        ])

    assert rc == 0
    payload = dispatch.call_args.kwargs["payload"]
    assert payload["files"] == [{
        "slug": "FLEET-COMMS",
        "path": str(handoff.resolve()),
        "text": rendered,
    }]


@pytest.mark.parametrize("slugs", [[], ["MISSION", "VISION"]])
def test_content_file_requires_exactly_one_explicit_slug(
    tmp_path: Path,
    slugs: list[str],
) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text("rendered\n", encoding="utf-8")

    with patch.object(strategy_render._helpers, "ensure_handlers_loaded"), \
            patch.object(strategy_render, "build_actor", return_value=object()), \
            patch.object(strategy_render, "strategy_target", return_value=object()), \
            patch.object(
                strategy_render,
                "resolve_target_root_for_cli",
                return_value=tmp_path,
            ), \
            patch.object(strategy_render, "call_dispatcher") as dispatch:
        rc = strategy_render.strategy_ingest([
            *slugs, "--content-file", str(handoff),
        ])

    assert rc == 2
    dispatch.assert_not_called()


def test_write_back_skips_target_root_registered_to_another_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # field note 49342: the written docs already landed in the DB
    # (this response models that success), so the command still
    # succeeds — only the local header-advance write is skipped when
    # target_root turns out to be a different project's checkout.
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

    handoff = other_checkout / "FLEET-COMMS.md"
    handoff.write_text("<!-- h -->\n# Fleet communications\n", encoding="utf-8")
    written_response = FunctionCallResponse(
        success=True, function="strategy.ingest.run", version="v1",
        request_id="mismatch-test",
        result={
            "project_id": 1, "project_slug": "yoke",
            "docs": [{
                "slug": "FLEET-COMMS", "status": "written",
                "old_lines": 1, "new_lines": 2, "line_delta": 1,
                "file_text": "<!-- h2 -->\n# Fleet communications\n",
                "archived": False,
            }],
        },
    )

    with patch.object(strategy_render._helpers, "ensure_handlers_loaded"), \
            patch.object(strategy_render, "build_actor", return_value=object()), \
            patch.object(strategy_render, "strategy_target", return_value=object()), \
            patch.object(
                strategy_render, "call_dispatcher", return_value=written_response,
            ):
        rc = strategy_render.strategy_ingest([
            "FLEET-COMMS", "--content-file", str(handoff),
            "--target-root", str(other_checkout),
        ])

    assert rc == 0
    # The write-back is skipped: no header-advanced file lands under the
    # other project's checkout.
    assert not (other_checkout / ".yoke").exists()
