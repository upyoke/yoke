"""Collectors for the Atlas integrity audit.

Each ``collect_*`` returns a deterministic, JSON-serialisable dict shaped
to the contract documented in ``atlas_integrity_audit``. Keep this module
narrow: no rendering, no writing, no I/O beyond reads.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


_TEACHING_GLOBS = (
    ".agents/skills/yoke/**/*.md",
    "runtime/agents/*.md",
    "runtime/harness/claude/agents/yoke-*.md",
    "runtime/harness/codex/agents/yoke-*.toml",
    "packages/yoke-core/src/yoke_core/domain/schema_api_context*.py",
)


def collect_function_registry() -> Dict[str, Any]:
    """Read every entry from the live ``yoke_function_registry``.

    Loads handlers before reading so the dispatcher-driven registration
    is honoured. Returns a stable rows list plus counts.
    """
    from yoke_core.domain.yoke_function_dispatch import _ensure_handlers_registered
    _ensure_handlers_registered()
    from yoke_core.domain.yoke_function_registry import list_entries

    rows: List[Dict[str, Any]] = []
    for entry in list_entries():
        rows.append({
            "function_id": entry.function_id,
            "version": entry.version,
            "stability": entry.stability,
            "owner_module": entry.owner_module,
            "target_kinds": list(entry.target_kinds),
            "side_effects": list(entry.side_effects),
            "emitted_event_names": list(entry.emitted_event_names),
            "guardrails": list(entry.guardrails),
            "adapter_status": entry.adapter_status,
            "replacement_function_id": entry.replacement_function_id,
            "removal_target_version": entry.removal_target_version,
            "claim_required_kind": entry.claim_required_kind,
        })
    rows.sort(key=lambda r: r["function_id"])
    by_stability: Dict[str, int] = {}
    by_adapter: Dict[str, int] = {}
    for r in rows:
        by_stability[r["stability"]] = by_stability.get(r["stability"], 0) + 1
        by_adapter[r["adapter_status"]] = by_adapter.get(r["adapter_status"], 0) + 1
    return {
        "count": len(rows),
        "by_stability": by_stability,
        "by_adapter_status": by_adapter,
        "rows": rows,
    }


def collect_subcommand_registry() -> Dict[str, Any]:
    """Read every ``yoke <subcommand>`` adapter row.

    Includes both the primary ``SUBCOMMAND_REGISTRY`` (mechanically
    grammar-translated from function ids) and ``SUBCOMMAND_ALIAS_REGISTRY``
    (operator-intuitive aliases that route to an existing function id).
    Both surfaces are reachable from the agent CLI; the audit treats them
    uniformly as wrapped reach. Alias rows are tagged ``alias=True`` for
    diagnostic value.
    """
    from yoke_cli.commands.registry import (
        SUBCOMMAND_ALIAS_REGISTRY,
        SUBCOMMAND_REGISTRY,
    )
    from yoke_cli.commands.flag_adapters import ADAPTER_USAGE

    def _row(cli_tokens, function_id, is_alias):
        usage = ADAPTER_USAGE.get(function_id, "")
        return {
            "cli_tokens": list(cli_tokens),
            "cli_form": "yoke " + " ".join(cli_tokens),
            "function_id": function_id,
            "family": function_id.split(".", 1)[0],
            "has_usage_line": bool(usage),
            "usage": usage,
            "alias": is_alias,
        }

    rows: List[Dict[str, Any]] = []
    for cli_tokens, (function_id, _adapter) in sorted(SUBCOMMAND_REGISTRY.items()):
        rows.append(_row(cli_tokens, function_id, False))
    for cli_tokens, (function_id, _adapter) in sorted(SUBCOMMAND_ALIAS_REGISTRY.items()):
        rows.append(_row(cli_tokens, function_id, True))
    return {"count": len(rows), "rows": rows}


def collect_operation_tracker() -> Dict[str, Any]:
    """Read every classified row from ``yoke_operation_inventory``."""
    from yoke_cli.operation_inventory import all_entries
    rows: List[Dict[str, Any]] = []
    for entry in all_entries():
        rows.append({
            "shell_form": entry.shell_form,
            "family": entry.family,
            "status": entry.status,
            "reason": entry.reason,
            "proposed_function_id": entry.proposed_function_id,
        })
    by_status: Dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {"count": len(rows), "by_status": by_status, "rows": rows}


def _capture_cli_help(argv: List[str]) -> Tuple[str, int, str]:
    """Invoke the in-process yoke CLI with ``argv`` and capture output."""
    from yoke_cli.main import main as cli_main
    buf_out, buf_err = io.StringIO(), io.StringIO()
    rc: int
    try:
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = cli_main(argv)
    except SystemExit as exc:
        rc = int(exc.code) if isinstance(exc.code, int) else 1
    return buf_out.getvalue(), rc, buf_err.getvalue()


def collect_help_pages(yoke_cli: Dict[str, Any]) -> Dict[str, Any]:
    """Capture top-level ``yoke --help`` plus every per-subcommand help."""
    top_body, top_rc, _ = _capture_cli_help(["--help"])
    per: Dict[str, Dict[str, Any]] = {}
    covered = 0
    for row in yoke_cli["rows"]:
        tokens = row["cli_tokens"]
        body, rc, stderr = _capture_cli_help(tokens + ["--help"])
        # argparse --help paths exit rc=0; missing-arg paths exit rc=2 with
        # usage text on stderr. Both count as "has usable help".
        usable = bool(body.strip()) or bool(stderr.strip())
        if usable:
            covered += 1
        per[" ".join(tokens)] = {
            "exit_code": rc,
            "body": body,
            "stderr": stderr,
            "has_usage_line": bool(row["has_usage_line"]),
        }
    total = yoke_cli["count"]
    return {
        "top_level": {"exit_code": top_rc, "body": top_body},
        "per_subcommand": per,
        "coverage": {
            "total": total,
            "with_usable_help": covered,
            "missing": total - covered,
        },
    }


def collect_teaching_places(target_root: Path) -> Dict[str, Any]:
    """Inventory packets, rendered agents, skill files."""
    paths: Dict[str, List[str]] = {}
    for glob in _TEACHING_GLOBS:
        matched = sorted(
            p.relative_to(target_root).as_posix()
            for p in target_root.glob(glob) if p.is_file()
        )
        paths[glob] = matched
    return {
        "groups": paths,
        "totals": {glob: len(items) for glob, items in paths.items()},
    }


def collect_recipes(target_root: Path) -> Dict[str, Any]:
    """Run the skill-recipe smoke harness and surface every verdict."""
    from yoke_core.tools.verify_skill_recipes import verify_skill_root
    skill_root = target_root / ".agents" / "skills" / "yoke"
    if not skill_root.is_dir():
        return {
            "total": 0, "template_skipped": 0, "failed": 0,
            "verdicts": [], "skill_root_missing": True,
        }
    verdicts = verify_skill_root(skill_root)
    rows = [asdict(v) for v in verdicts]
    return {
        "total": len(rows),
        "template_skipped": sum(1 for r in rows if r["template_skipped"]),
        "failed": sum(1 for r in rows if not r["ok"]),
        "verdicts": rows,
    }


_FIELD_NOTE_FOOTER_HINTS = (
    "yoke ouroboros field-note append",
    "yoke-ouroboros-field-note-append",
)


def collect_lints(target_root: Path) -> Dict[str, Any]:
    """Inventory ``runtime/api/domain/lint_*.py`` modules.

    Records, per file, whether the static body carries the field-note
    footer / denial recipe references that the inline-short doctrine
    expects.
    """
    rows: List[Dict[str, Any]] = []
    for path in sorted((target_root / "runtime" / "api" / "domain").glob("lint_*.py")):
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        has_field_note = any(hint in body for hint in _FIELD_NOTE_FOOTER_HINTS)
        has_denial_text = "BLOCKED" in body or "deny" in body or "denied" in body
        rows.append({
            "module": path.relative_to(target_root).as_posix(),
            "has_field_note_reference": has_field_note,
            "has_denial_text": has_denial_text,
        })
    return {
        "count": len(rows),
        "with_field_note_reference": sum(1 for r in rows if r["has_field_note_reference"]),
        "with_denial_text": sum(1 for r in rows if r["has_denial_text"]),
        "rows": rows,
    }


def collect_field_notes() -> Dict[str, Any]:
    """Read recent ouroboros field-notes through the CLI transport surface."""
    surface_status = "agent_facing"
    try:
        from yoke_cli.transport.dispatcher import call_dispatcher
        from yoke_contracts.api.function_call import ActorContext, TargetRef

        response = call_dispatcher(
            function_id="ouroboros.field_note.list",
            target=TargetRef(kind="global", project_id="yoke"),
            payload={
                "category_prefix": "field-note-",
                "limit": 50,
            },
            actor=ActorContext(session_id="atlas-integrity-audit"),
        )
    except Exception as exc:
        return {
            "count": 0, "rows": [],
            "read_surface_status": "agent_facing_error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not response.success:
        message = response.error.message if response.error else "unknown error"
        return {
            "count": 0, "rows": [],
            "read_surface_status": "agent_facing_error",
            "error": message,
        }
    rows = response.result.get("entries", [])
    return {
        "count": len(rows), "rows": rows,
        "read_surface_status": surface_status,
    }
