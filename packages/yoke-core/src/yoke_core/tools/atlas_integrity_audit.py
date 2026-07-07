"""Atlas integrity audit — read-only Yoke surface audit.

Read-only collection of live facts from the Yoke tree: function
registry, yoke CLI, operation tracker, help pages, skill recipes,
teaching places, lints, field-notes, contradictions. Writes a stable
JSON report consumed by ``atlas_render_docs`` and ``doctor_hc_atlas``.

Workspace-anchored: callers pass ``--target-root`` explicitly; the
writer honours the standard workspace authority guard.

Top-level keys: generated_at, function_registry, yoke_cli,
operation_tracker, help_pages, teaching_places, recipes, lints,
field_notes, contradictions, followup_candidates, summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)
from yoke_core.tools.atlas_integrity_collect import (
    collect_field_notes,
    collect_function_registry,
    collect_help_pages,
    collect_lints,
    collect_operation_tracker,
    collect_recipes,
    collect_subcommand_registry,
    collect_teaching_places,
)


# Seed contradictions the runner always considers. Resolved against
# live state at collection time; the audit records the live shape and
# flags any open mismatch.
SEED_CONTRADICTIONS: List[Dict[str, str]] = [
    {
        "id": "function-inventory-empty-registry-mismatch",
        "kind": "promise-vs-live",
        "surface": "docs/function-inventory.md",
        "claim": "docs/function-inventory.md claims the registry is empty",
        "live_truth": "yoke_function_registry.list_entries() is non-empty",
        "resolution_hint": "Replace docs/function-inventory.md with docs/atlas.md",
    },
    {
        "id": "claims-work-holder-get-flag-vs-positional",
        "kind": "ticket-promise-vs-live",
        "surface": "yoke claims work holder-get",
        "claim": "Claim-holder docs promised `yoke claims work holder-get --item YOK-N`",
        "live_truth": "live `yoke claims work holder-get` accepts positional <YOK-N>",
        "resolution_hint": "Either land the --item flag adapter or correct the promise",
    },
]


def _resolve_seed_contradiction(
    seed: Dict[str, str],
    cli_help: Dict[str, Any],
    doc_state: Dict[str, Any],
) -> Dict[str, Any]:
    row = dict(seed)
    row["status"] = "open"
    if seed["id"] == "function-inventory-empty-registry-mismatch":
        if not doc_state.get("exists"):
            row["status"] = "resolved"
            row["resolution_note"] = "docs/function-inventory.md deleted (replaced by docs/atlas.md)"
        elif not doc_state.get("claims_empty_registry"):
            row["status"] = "resolved"
            row["resolution_note"] = "docs/function-inventory.md no longer claims an empty registry"
    elif seed["id"] == "claims-work-holder-get-flag-vs-positional":
        help_text = (
            cli_help.get("per_subcommand", {})
            .get("claims work holder-get", {}).get("body", "")
        )
        if "--item" in help_text:
            row["status"] = "resolved"
            row["resolution_note"] = "live help now accepts --item"
    return row


def _function_inventory_doc_state(target_root: Path) -> Dict[str, Any]:
    path = target_root / "docs" / "function-inventory.md"
    if not path.exists():
        return {"exists": False, "claims_empty_registry": False}
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "exists": True,
        "claims_empty_registry": (
            "Registry is reachable but empty" in text
            or "Function registry not yet wired" in text
        ),
    }


def _build_followup_candidates(
    *,
    operation_tracker: Dict[str, Any],
    contradictions: List[Dict[str, Any]],
    field_notes: Dict[str, Any],
    recipes: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    pending = [r for r in operation_tracker["rows"] if r["status"] == "pending"]
    if pending:
        candidates.append({
            "id": "pending-cli-adapter-conversions",
            "category": "cloud_blocker",
            "title": f"{len(pending)} handler-registration rows await a yoke CLI adapter",
            "evidence": [
                {"shell_form": r["shell_form"], "proposed_function_id": r.get("proposed_function_id")}
                for r in pending
            ],
        })
    open_rows = [r for r in contradictions if r["status"] == "open"]
    if open_rows:
        candidates.append({
            "id": "open-contradictions",
            "category": "teaching_drift",
            "title": f"{len(open_rows)} open promise-vs-live contradictions",
            "evidence": [{"id": r["id"], "surface": r["surface"]} for r in open_rows],
        })
    if field_notes.get("read_surface_status") != "agent_facing":
        candidates.append({
            "id": "field-note-read-surface-gap",
            "category": "teaching_drift",
            "title": "Field-note hotspot read through the agent-facing surface is unhealthy",
            "evidence": [field_notes.get("read_surface_status", "unknown")],
        })
    failed = [v for v in recipes["verdicts"] if not v["ok"]]
    if failed:
        candidates.append({
            "id": "failing-skill-recipes",
            "category": "teaching_drift",
            "title": f"{len(failed)} skill-body recipes fail smoke dispatch",
            "evidence": [
                {"file": v["file"], "line": v["line_number"], "recipe": v["recipe"], "error": v["error"]}
                for v in failed
            ],
        })
    return candidates


def _summary(
    function_registry: Dict[str, Any],
    yoke_cli: Dict[str, Any],
    operation_tracker: Dict[str, Any],
    help_pages: Dict[str, Any],
    recipes: Dict[str, Any],
    field_notes: Dict[str, Any],
    contradictions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    status_counts: Dict[str, int] = {}
    for row in operation_tracker["rows"]:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    return {
        "function_ids": function_registry["count"],
        "yoke_cli_subcommands": yoke_cli["count"],
        "operation_tracker": status_counts,
        "subcommand_help_coverage": help_pages["coverage"],
        "recipes": {
            "total": recipes["total"],
            "template_skipped": recipes["template_skipped"],
            "failed": recipes["failed"],
        },
        "field_notes_recent": field_notes.get("count", 0),
        "contradictions": {
            "total": len(contradictions),
            "open": sum(1 for c in contradictions if c["status"] == "open"),
        },
    }


def build_report(
    target_root: Path, *, generated_at: str | None = None,
) -> Dict[str, Any]:
    """Collect every live surface and return the stable JSON report dict."""
    function_registry = collect_function_registry()
    yoke_cli = collect_subcommand_registry()
    operation_tracker = collect_operation_tracker()
    help_pages = collect_help_pages(yoke_cli)
    teaching_places = collect_teaching_places(target_root)
    recipes = collect_recipes(target_root)
    lints = collect_lints(target_root)
    field_notes = collect_field_notes()
    doc_state = _function_inventory_doc_state(target_root)
    contradictions = [
        _resolve_seed_contradiction(seed, help_pages, doc_state)
        for seed in SEED_CONTRADICTIONS
    ]
    followup = _build_followup_candidates(
        operation_tracker=operation_tracker, contradictions=contradictions,
        field_notes=field_notes, recipes=recipes,
    )
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "generated_at": generated_at,
        "function_registry": function_registry,
        "yoke_cli": yoke_cli,
        "operation_tracker": operation_tracker,
        "help_pages": help_pages,
        "teaching_places": teaching_places,
        "recipes": recipes,
        "lints": lints,
        "field_notes": field_notes,
        "contradictions": contradictions,
        "followup_candidates": followup,
        "summary": _summary(
            function_registry, yoke_cli, operation_tracker, help_pages,
            recipes, field_notes, contradictions,
        ),
    }


def serialise(report: Dict[str, Any]) -> str:
    """Stable JSON serialisation (sorted keys, 2-space indent)."""
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def write_report(report: Dict[str, Any], output: Path) -> Path:
    """Write the report honouring the workspace authority guard."""
    assert_target_under_session_work_authority(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialise(report), encoding="utf-8")
    return output


def _resolve_target_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        if (parent / "runtime" / "api" / "tools").is_dir():
            return parent
    raise RuntimeError("could not infer --target-root; pass it explicitly")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas_integrity_audit",
        description="Read-only audit of Yoke's live agent-facing surfaces.",
    )
    parser.add_argument("--target-root", default=None)
    parser.add_argument("--output", default=None,
                        help="Write JSON report to PATH (stdout when omitted).")
    parser.add_argument("--print-summary", action="store_true",
                        help="Also print summary block to stderr.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    target_root = _resolve_target_root(args.target_root)
    report = build_report(target_root)
    if args.output:
        output = Path(args.output).resolve()
        write_report(report, output)
        if args.print_summary:
            print(json.dumps(report["summary"], indent=2, sort_keys=True),
                  file=sys.stderr)
        print(output)
    else:
        sys.stdout.write(serialise(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
