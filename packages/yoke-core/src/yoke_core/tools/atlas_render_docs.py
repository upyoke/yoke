"""Render ``docs/atlas.md`` from the Atlas integrity audit.

``render`` writes under ``--target-root``; ``check`` exits 1 when stale
(``generated_at`` and live-DB sections are stripped from the comparison).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)
from yoke_core.tools.atlas_integrity_audit import build_report
from yoke_core.tools.atlas_render_docs_sections import (
    _render_contradictions,
    _render_curl_floor,
    _render_field_notes,
    _render_next_slice,
    _render_teaching,
)
from yoke_core.tools.atlas_render_docs_tables import _md_table


_ATLAS_RELPATH = "docs/atlas.md"
_TIMESTAMP_LINE_RE = re.compile(
    r"^_Audit generated_at: .*_$", re.MULTILINE
)
_TIMESTAMP_PLACEHOLDER = "_Audit generated_at: <stripped for diff>_"
# Live DB sections (field-notes + next-slice derived from them) churn;
# strip them so tree-only CI matches a laptop-rendered atlas.md.
_FIELD_NOTE_SECTION_RE = re.compile(
    r"^## 7\. Field-note hotspots\n.*?(?=^## )",
    re.MULTILINE | re.DOTALL,
)
_FIELD_NOTE_PLACEHOLDER = "## 7. Field-note hotspots\n\n_<live DB section, stripped for diff>_\n\n"
_NEXT_SLICE_SECTION_RE = re.compile(
    r"^## 9\. Next-slice recommendation\n.*?(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
_NEXT_SLICE_PLACEHOLDER = (
    "## 9. Next-slice recommendation\n\n"
    "_<live DB section, stripped for diff>_\n\n"
)
_FIELD_NOTE_SUMMARY_RE = re.compile(
    r"^- Recent field-notes inspected: \d+$",
    re.MULTILINE,
)
_FIELD_NOTE_SUMMARY_PLACEHOLDER = (
    "- Recent field-notes inspected: <live DB count>"
)


def _render_summary(report: Dict[str, Any]) -> List[str]:
    s = report["summary"]
    tracker = s["operation_tracker"]
    out = ["## 1. Summary", ""]
    out.append(f"- Function ids registered: **{s['function_ids']}**")
    internal = report["function_registry"]["by_adapter_status"].get(
        "internal", 0,
    )
    if internal:
        out.append(
            "- Internal dispatch-only functions without CLI adapters: "
            f"**{internal}**"
        )
    out.append(
        f"- `yoke` CLI subcommands: **{s['yoke_cli_subcommands']}** "
        f"({s['subcommand_help_coverage']['with_usable_help']} carry usable "
        f"`--help`)"
    )
    out.append(
        "- Operation tracker: "
        f"**{tracker.get('wrapped', 0)} wrapped**, "
        f"{tracker.get('tool_cli', 0)} tool_cli, "
        f"{tracker.get('permanent', 0)} permanent, "
        f"{tracker.get('pending', 0)} pending"
    )
    out.append(
        "- Skill-body recipes: "
        f"{s['recipes']['total']} total "
        f"({s['recipes']['template_skipped']} template-skipped, "
        f"{s['recipes']['failed']} failing)"
    )
    out.append(f"- Recent field-notes inspected: {s['field_notes_recent']}")
    out.append(
        f"- Contradictions: **{s['contradictions']['open']} open** "
        f"(of {s['contradictions']['total']} tracked)"
    )
    out.append("")
    return out


def _render_wrapped_roster(report: Dict[str, Any]) -> List[str]:
    out = ["## 2. Wrapped operation roster", ""]
    cli_rows = [
        row
        for row in report["yoke_cli"]["rows"]
        if row.get("dispatch_kind", "dispatcher") == "dispatcher"
    ]
    out.append(
        f"Wrapped dispatcher-backed `yoke <subcommand>` adapters: "
        f"**{len(cli_rows)}** "
        f"(operation tracker confirms {report['operation_tracker']['by_status'].get('wrapped', 0)} "
        "wrapped rows)."
    )
    out.append("")
    if not cli_rows:
        out.append("_No dispatcher-backed `yoke` subcommands registered._")
        out.append("")
        return out
    help_per = report["help_pages"]["per_subcommand"]
    rendered: List[Sequence[str]] = []
    for row in sorted(cli_rows, key=lambda r: (r["family"], r["function_id"])):
        tokens = " ".join(row["cli_tokens"])
        body = help_per.get(tokens, {}).get("body", "")
        stderr = help_per.get(tokens, {}).get("stderr", "")
        help_status = "ok" if (body.strip() or stderr.strip()) else "missing"
        rendered.append(
            (row["family"], f"`{row['cli_form']}`", f"`{row['function_id']}`", help_status)
        )
    out.extend(_md_table(
        ("family", "yoke form", "function_id", "help"),
        rendered,
    ))
    out.append("")
    return out


def _render_tool_cli_roster(report: Dict[str, Any]) -> List[str]:
    out = ["## 3. Tool-shaped CLI roster", ""]
    rows = [
        r for r in report["operation_tracker"]["rows"]
        if r["status"] == "tool_cli"
    ]
    out.append(
        "First-class local `yoke` adapters that run subprocess tools without "
        "a dispatcher function id."
    )
    out.append("")
    if not rows:
        out.append("_No tool-shaped CLI adapters registered._")
        out.append("")
        return out
    out.extend(_md_table(
        ("family", "yoke form", "reason"),
        sorted(
            (
                (r["family"], f"`{r['shell_form']}`", r["reason"])
                for r in rows
            ),
            key=lambda r: (r[0], r[1]),
        ),
    ))
    out.append("")
    return out


def _render_permanent_roster(report: Dict[str, Any]) -> List[str]:
    out = ["## 4. Permanent command-shaped boundary roster", ""]
    rows = [r for r in report["operation_tracker"]["rows"] if r["status"] == "permanent"]
    if not rows:
        out.append("_No retained command-shaped boundaries._")
    else:
        out.extend(_md_table(
            ("family", "shell_form", "reason", "source owner"),
            sorted(
                (
                    (
                        r["family"],
                        f"`{r['shell_form']}`",
                        r["reason"],
                        r.get("source_owner") or "—",
                    )
                    for r in rows
                ),
                key=lambda r: (r[0], r[1]),
            ),
        ))
    out.extend([
        "",
        "### Human-only stranded work-claim release",
        "",
        "When another session has ended but still owns a work claim, a human "
        "operator may release that exact claim through the retained "
        "operator-debug boundary:",
        "",
        "```sh",
        "python3 -m yoke_core.api.service_client claim-release \\",
        " --item PREFIX-N --claim-id CLAIM_ID --reason \"stranded session\"",
        "```",
        "",
        "This is not an agent self-release recipe. It refuses hook contexts, "
        "records the reason on `OperatorClaimOverride`, and must only target a "
        "claim the operator has verified is stranded.",
    ])
    out.append("")
    return out


def _render_pending_roster(report: Dict[str, Any]) -> List[str]:
    out = ["## 5. Pending handler-registration roster", ""]
    rows = [r for r in report["operation_tracker"]["rows"] if r["status"] == "pending"]
    if not rows:
        out.append("_No pending handler-registration rows._")
        out.append("")
        return out
    out.extend(_md_table(
        ("family", "current fallback", "proposed function_id", "reason"),
        sorted(
            (
                (r["family"], f"`{r['shell_form']}`",
                 f"`{r['proposed_function_id']}`", r["reason"])
                for r in rows
            ),
            key=lambda r: (r[0], r[1]),
        ),
    ))
    out.append("")
    return out


def _header(report: Dict[str, Any]) -> List[str]:
    return [
        "# Yoke Atlas",
        "",
        "Operator-readable inventory of Yoke's agent-facing surfaces. "
        "Rendered by `python3 -m yoke_core.tools.atlas_render_docs render` "
        "from the Atlas integrity audit JSON.",
        "",
        f"_Audit generated_at: {report['generated_at']}_",
        "",
    ]


def render(report: Dict[str, Any]) -> str:
    """Render the audit report into the canonical Markdown body."""
    lines: List[str] = []
    lines.extend(_header(report))
    lines.extend(_render_summary(report))
    lines.extend(_render_wrapped_roster(report))
    lines.extend(_render_tool_cli_roster(report))
    lines.extend(_render_permanent_roster(report))
    lines.extend(_render_pending_roster(report))
    lines.extend(_render_teaching(report))
    lines.extend(_render_field_notes(report))
    lines.extend(_render_contradictions(report))
    lines.extend(_render_next_slice(report))
    lines.extend(_render_curl_floor())
    return "\n".join(lines).rstrip() + "\n"


def write(target_root: Path, *, body: str, output: Path | None = None) -> Path:
    """Write ``body`` to ``docs/atlas.md`` under ``target_root``."""
    out = output if output is not None else target_root / _ATLAS_RELPATH
    assert_target_under_session_work_authority(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out


def _normalise(body: str) -> str:
    body = _TIMESTAMP_LINE_RE.sub(_TIMESTAMP_PLACEHOLDER, body)
    body = _FIELD_NOTE_SUMMARY_RE.sub(
        _FIELD_NOTE_SUMMARY_PLACEHOLDER,
        body,
    )
    body = _FIELD_NOTE_SECTION_RE.sub(_FIELD_NOTE_PLACEHOLDER, body)
    return _NEXT_SLICE_SECTION_RE.sub(_NEXT_SLICE_PLACEHOLDER, body)


def is_stale(target_root: Path, *, body: str) -> bool:
    """Return True iff ``docs/atlas.md`` is missing or content-different.

    The audit timestamp is normalised out so re-rendering with a new
    ``generated_at`` does not flap the check.
    """
    out = target_root / _ATLAS_RELPATH
    if not out.exists():
        return True
    existing = out.read_text(encoding="utf-8")
    return _normalise(existing) != _normalise(body)


def _load_or_build(target_root: Path, from_report: str | None) -> Dict[str, Any]:
    if from_report:
        path = Path(from_report).resolve()
        return json.loads(path.read_text(encoding="utf-8"))
    return build_report(target_root)


def _progress(message: str) -> None:
    sys.stderr.write(f"atlas_render_docs: {message}\n")
    sys.stderr.flush()


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
        prog="atlas_render_docs",
        description="Render docs/atlas.md from the Atlas integrity audit report.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_render = sub.add_parser("render", help="Write docs/atlas.md.")
    p_render.add_argument("--target-root", default=None)
    p_render.add_argument("--from-report", default=None,
                          help="Load a pre-built JSON report instead of building one.")
    p_render.add_argument("--output", default=None)
    p_check = sub.add_parser("check", help="Print rendered body and exit 1 if stale.")
    p_check.add_argument("--target-root", default=None)
    p_check.add_argument("--from-report", default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    target_root = _resolve_target_root(args.target_root)
    if args.from_report:
        _progress(f"loading report {args.from_report}")
    else:
        _progress("building audit report")
    report = _load_or_build(target_root, args.from_report)
    _progress("rendering docs/atlas.md")
    body = render(report)
    if args.cmd == "render":
        out = Path(args.output).resolve() if args.output else None
        _progress("writing docs/atlas.md")
        path = write(target_root, body=body, output=out)
        print(path)
        return 0
    elif args.cmd == "check":
        sys.stdout.write(body)
        return 1 if is_stale(target_root, body=body) else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
