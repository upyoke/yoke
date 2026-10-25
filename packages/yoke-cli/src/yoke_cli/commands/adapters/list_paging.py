"""Shared CLI page inputs and bounded list summaries."""

from __future__ import annotations

import argparse
import json

from yoke_contracts.api.function_call import FunctionError
from yoke_contracts.list_paging import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from yoke_cli.commands._helpers import dispatch_and_emit
from yoke_cli.transport.human_values import write_human
from yoke_cli.transport.output_limit import full_output_requested


def _limit(raw: str) -> int:
    value = int(raw)
    if not 1 <= value <= MAX_LIST_LIMIT:
        raise argparse.ArgumentTypeError(f"pass --limit 1..{MAX_LIST_LIMIT}")
    return value


def _offset(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("pass --offset 0 or greater")
    return value


def add_page_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=_limit,
        default=DEFAULT_LIST_LIMIT,
        metavar="N",
        help="Most rows per page (default: 25; maximum: 500).",
    )
    parser.add_argument(
        "--offset",
        type=_offset,
        default=0,
        metavar="N",
        help="Rows to skip; use the next offset printed by the list.",
    )
    parser.epilog = (parser.epilog or "") + (
        "\nLists show summaries. Keep the same filters and use --offset for the "
        "next page; --full expands details on the same page. --json keeps all page fields."
    )


def page_payload(parsed) -> dict:
    return {"limit": parsed.limit, "offset": parsed.offset}


# List summaries retain identity, state and the values needed to choose a detail read.
_COLUMNS = {
    "qa.requirement.list": ("id", "qa_kind", "method_id", "qa_phase"),
    "qa.run.list": (
        "id",
        "qa_requirement_id",
        "execution_status",
        "case_outcome",
        "verdict",
    ),
    "qa.method.list": ("id", "name", "runner_id", "verdict_path"),
    "qa.plan.list": ("id", "slug", "case_count", "last_outcome"),
    "qa.activity.list": (
        "requirement_id",
        "run_id",
        "method_id",
        "outcome",
        "happened_at",
    ),
    "claims.path.list": ("id", "state", "declared_paths", "task_num"),
    "items.dependency.list": (
        "direction",
        "other_item",
        "gate_point",
        "satisfaction",
        "rationale",
    ),
    "item_worktrees.list": ("id", "lane_role", "branch", "state", "path"),
    "item_worktrees.inventory": ("public_ref", "status", "branch", "state", "path"),
    "epic_tasks.list.run": ("task_num", "title", "status", "dependencies"),
    "strategy.doc.list": ("slug", "updated_at", "bytes", "archived"),
    "workflow_item.epic_progress_note.list": ("id", "note_num", "created_at", "body"),
}
_KEYS = {
    "claims.path.list": "claims",
    "items.dependency.list": "dependencies",
    "item_worktrees.list": "worktrees",
    "item_worktrees.inventory": "lanes",
    "epic_tasks.list.run": "tasks",
    "strategy.doc.list": "docs",
}
_DETAILS = {
    "qa.requirement.list": "yoke qa requirement get N --full",
    "qa.run.list": "yoke qa run get --run-id N --full",
    "qa.method.list": "yoke qa method get METHOD --full",
    "qa.plan.list": "yoke qa plan get PLAN-ID --project P --full",
    "qa.activity.list": "yoke qa requirement get N --full; yoke qa run get --run-id N --full",
    "claims.path.list": "yoke claims path get CLAIM-ID --full",
}


def _cell(value) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(str(value if value is not None else "-").split())
    raw = text.encode("utf-8")
    return raw[:100].decode("utf-8", errors="ignore") + ("…" if len(raw) > 100 else "")


def list_writer(function_id: str):
    def write(response, stdout, stderr):
        result = response.result or {}
        if full_output_requested():
            write_human(result, stdout)
            return
        if function_id == "items.dependency.list" and "integration_gate" in result:
            gate = result["integration_gate"]
            write_human(
                {
                    "integration_gate": {
                        **{k: v for k, v in gate.items() if k != "blockers"},
                        "blocker_count": len(gate.get("blockers") or []),
                    }
                },
                stdout,
            )
        key = _KEYS.get(function_id, "rows")
        rows = result.get(key) or []
        columns = _COLUMNS[function_id]
        lines = [" | ".join(columns)]
        size = len(lines[0].encode("utf-8"))
        served = 0
        for row in rows:
            line = " | ".join(_cell(row.get(field)) for field in columns)
            cost = len(line.encode("utf-8")) + 1
            if size + cost > 24000:
                break
            lines.append(line)
            size += cost
            served += 1
        print("\n".join(lines) if rows else f"{key}: no entries.", file=stdout)
        offset = int(result.get("offset") or 0)
        next_offset = (
            offset + served if served < len(rows) else result.get("next_offset")
        )
        if next_offset is not None:
            print(f"More rows. Next page: --offset {next_offset}", file=stdout)
        detail = _DETAILS.get(
            function_id, "repeat this list with --full for complete page details"
        )
        print(f"Details: {detail}. --json keeps all page fields.", file=stdout)

    return write


def dispatch_list(*, parsed, **kwargs) -> int:
    function_id = kwargs["function_id"]
    kwargs["payload"] = {**kwargs.get("payload", {}), **page_payload(parsed)}
    kwargs["human_writer"] = list_writer(function_id)

    def require_page(response, actor):
        if not response.success:
            return response
        result = response.result or {}
        rows = result.get(_KEYS.get(function_id, "rows")) or []
        if (parsed.offset and result.get("offset") != parsed.offset) or len(
            rows
        ) > parsed.limit:
            return response.model_copy(
                update={
                    "success": False,
                    "result": {},
                    "error": FunctionError(
                        code="list_paging_unavailable",
                        message="This control plane did not apply the requested list page.",
                        recovery_hint="Serving floor: next-release carrying limit/offset list reads. Upgrade the control plane and retry the same page.",
                    ),
                }
            )
        return response

    kwargs["response_recovery"] = require_page
    return dispatch_and_emit(**kwargs)
