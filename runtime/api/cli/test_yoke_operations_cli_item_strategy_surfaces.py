"""CLI envelopes for unified item pages and strategy execution surfaces."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_cli.commands.adapters.strategy_surfaces import USAGE_BY_FUNCTION_ID
from yoke_core.api.service_client_structured_api_adapter_inventory_strategy import (
    STRATEGY_ADAPTERS,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _run(*argv: str) -> tuple[int, FunctionCallRequest]:
    captured: list[FunctionCallRequest] = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            request_id=request.request_id,
            version=request.version,
            result={},
        )

    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "item-strategy-test"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        result = cli_main(list(argv))
    assert captured
    return result, captured[-1]


def test_item_overview_and_detail_keep_their_distinct_targets() -> None:
    result, overview = _run(
        "items",
        "overview",
        "list",
        "--project",
        "yoke",
        "--limit",
        "25",
    )
    assert result == 0
    assert overview.function == "items.overview.list"
    assert overview.target.kind == "global"
    assert overview.payload == {"project": "yoke", "limit": 25}

    result, detail = _run(
        "items",
        "detail",
        "get",
        TEST_ITEM_REF,
        "--project",
        "yoke",
    )
    assert result == 0
    assert detail.function == "items.detail.get"
    assert detail.target.kind == "item"
    assert detail.target.item_ref == TEST_ITEM_REF
    assert detail.target.project_id == "yoke"
    assert detail.payload == {}


def test_strategy_surface_reads_and_revision_diff_keep_project_context() -> None:
    result, surface = _run(
        "strategy",
        "surface",
        "get",
        "WORKFLOW-TYPES",
        "--project",
        "yoke",
    )
    assert result == 0
    assert surface.function == "strategy.surface.get"
    assert surface.target.kind == "global"
    assert surface.target.project_id == "yoke"
    assert surface.payload == {"slug": "WORKFLOW-TYPES"}

    result, diff = _run(
        "strategy",
        "revision",
        "diff",
        "WORKFLOW-TYPES",
        "--from-revision",
        "2",
        "--to-revision",
        "4",
        "--project",
        "yoke",
    )
    assert result == 0
    assert diff.function == "strategy.revision.diff"
    assert diff.payload == {
        "slug": "WORKFLOW-TYPES",
        "from_revision": 2,
        "to_revision": 4,
    }


def test_strategy_restore_parent_and_coordination_payloads_are_typed() -> None:
    result, restore = _run(
        "strategy",
        "revision",
        "restore",
        "WORKFLOW-TYPES",
        "--revision",
        "3",
        "--base-updated-at",
        "2026-07-26T12:00:00Z",
        "--project",
        "yoke",
    )
    assert result == 0
    assert restore.function == "strategy.revision.restore"
    assert restore.payload["revision"] == 3
    assert restore.payload["base_updated_at"] == "2026-07-26T12:00:00Z"

    result, parent = _run(
        "strategy",
        "parent",
        "set",
        "WORKFLOW-TYPES",
        "--clear",
        "--project",
        "yoke",
    )
    assert result == 0
    assert parent.function == "strategy.parent.set"
    assert parent.payload == {
        "slug": "WORKFLOW-TYPES",
        "parent_slug": None,
    }

    result, coordination = _run(
        "strategy",
        "coordination",
        "append",
        "WORKFLOW-TYPES",
        "--section",
        "Session Notes",
        "--entry",
        "Registry cutover complete.",
        "--project",
        "yoke",
    )
    assert result == 0
    assert coordination.function == "strategy.coordination.append"
    assert coordination.payload["section"] == "Session Notes"
    assert coordination.payload["entry"] == "Registry cutover complete."


def test_strategy_execution_and_claim_commands_target_the_item() -> None:
    result, link = _run(
        "strategy",
        "execution",
        "link",
        TEST_ITEM_REF,
        "--slug",
        "WORKFLOW-TYPES",
        "--project",
        "yoke",
    )
    assert result == 0
    assert link.function == "strategy.execution.link"
    assert link.target.kind == "item"
    assert link.target.item_ref == TEST_ITEM_REF
    assert link.payload == {"slug": "WORKFLOW-TYPES"}

    result, release = _run(
        "strategy",
        "claim",
        "release",
        TEST_ITEM_REF,
        "--reason",
        "Execution document complete.",
        "--project",
        "yoke",
    )
    assert result == 0
    assert release.function == "strategy.claim.release"
    assert release.target.item_ref == TEST_ITEM_REF
    assert release.payload == {"reason": "Execution document complete."}

    result, release = _run(
        "strategy",
        "claim",
        "break-glass-release",
        TEST_ITEM_REF,
        "--reason",
        "Operator recovered an abandoned document claim.",
        "--project",
        "yoke",
    )
    assert result == 0
    assert release.function == "strategy.claim.break_glass_release"
    assert release.target.item_ref == TEST_ITEM_REF
    assert release.payload == {
        "reason": "Operator recovered an abandoned document claim."
    }


def test_strategy_claim_release_usage_advertises_optional_reason() -> None:
    expected = (
        "yoke strategy claim release (ITEM | PROCESS_KEY) "
        "[--reason TEXT] --project P"
    )
    assert USAGE_BY_FUNCTION_ID["strategy.claim.release"] == expected
    inventory = {entry.function_id: entry.cli_invocation for entry in STRATEGY_ADAPTERS}
    assert inventory["strategy.claim.release"] == expected


def test_strategy_claim_release_process_key_routes_to_work_release() -> None:
    result, req = _run(
        "strategy",
        "claim",
        "release",
        "STRATEGIZE",
        "--reason",
        "era closeout",
        "--project",
        "yoke",
    )
    assert result == 0
    assert req.function == "claims.work.release"
    assert req.target.kind == "global"
    assert req.payload == {
        "reason": "era closeout",
        "process_key": "STRATEGIZE",
        "project": "yoke",
    }


def test_strategy_claim_release_unknown_process_lists_known_keys() -> None:
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "item-strategy-test"}),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(io.StringIO()) as out,
        redirect_stderr(io.StringIO()),
    ):
        result = cli_main(
            ["strategy", "claim", "release", "CURRENT-PLAN", "--project", "yoke"]
        )
    assert result == 2
    combined = out.getvalue()
    assert "CURRENT-PLAN" in combined
    assert "STRATEGIZE" in combined
    assert "FEED" in combined
    assert "DOCTOR" in combined
