"""CLI coverage for strategy ingest handoff files."""

from __future__ import annotations

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
