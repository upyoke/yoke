"""Yoke doctor engine: CLI runner over the HC registry.

The ordered ``HEALTH_CHECKS`` list and every HC implementation live in
``yoke_core.engines.doctor_registry``. This module owns just the runner
contract: argument parsing, per-HC dispatch, report formatting, exit code.
``HealthCheck``, ``HEALTH_CHECKS``, and the HC functions are re-exported
from this module so existing callers (tests, ad hoc imports) keep working.

CLI::

    # One of --quick / --full / --only / --list-checks is REQUIRED so
    # callers make an explicit GitHub-quota choice:
    #   --quick      skip GitHub-dependent HCs (no gh subprocess calls)
    #   --full       run every HC including GitHub-dependent ones
    #   --only X     run only the named HC(s)
    #   --list-checks  info-only; list slugs and exit
    python3 -m yoke_core.engines.doctor --quick
    python3 -m yoke_core.engines.doctor --full
    python3 -m yoke_core.engines.doctor --only status-consistency
    python3 -m yoke_core.engines.doctor --only status-consistency,blocked-items
    python3 -m yoke_core.engines.doctor --quick --file /tmp/report.md
    python3 -m yoke_core.engines.doctor --full --project buzz
    python3 -m yoke_core.engines.doctor --list-checks

    # JSON mode pairs with the same explicit scope:
    python3 -m yoke_core.engines.doctor --json --quick
    python3 -m yoke_core.engines.doctor --json --only HC-status-consistency
    # The JSON adapter routes through doctor.run.run so the schema matches
    # the function-call surface byte-for-byte (modulo timestamps).

Exit code: 0 if no FAILs, 1 if any FAILs. Exit code 2 when no scope flag is
specified (caller must pick).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from yoke_core.domain.db_helpers import connect
from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER

# Star-import re-exports the full registry surface (HealthCheck, HEALTH_CHECKS,
# every HC function, and the underscore helpers tests depend on). The
# registry module declares the canonical public surface; everything imported
# here is exposed to legacy ``from yoke_core.engines.doctor import ...``
# callers without re-listing names in two places.
from yoke_core.engines.doctor_registry import *  # noqa: F401,F403
from yoke_core.engines.doctor_registry import (  # noqa: F401
    HEALTH_CHECKS,
    CheckResult,
    DoctorArgs,
    HealthCheck,
    RecordCollector,
    _column_exists,
    _DELEGATED_SYNC_HCS,
    _iso_to_epoch,
    _now_epoch,
    _github_auth_configured,
    _resolve_main_root,
    _resolve_repo_root,
    _run,
    _should_run_hc,
    _table_exists,
)


def _render_deferred_cleanup_addendum(conn) -> str:
    """List sessions currently in deferred-cleanup state.

    A deferred-cleanup session is one for which a
    ``HarnessSessionEndDeferred`` event fired without a follow-up
    ``HarnessSessionEnded`` for the same session. The operator should
    see when defense kicked in so they can investigate stalled sessions
    that never re-armed.
    """
    try:
        rows = conn.execute(
            "SELECT d.session_id, d.item_id, d.envelope, d.created_at "
            "FROM events d "
            "WHERE d.event_name = 'HarnessSessionEndDeferred' "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM events e "
            "    WHERE e.session_id = d.session_id "
            "      AND e.event_name = 'HarnessSessionEnded' "
            "      AND e.id > d.id"
            "  ) "
            "ORDER BY d.id DESC LIMIT 25"
        ).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["", "## Deferred-Cleanup Sessions",
             "Sessions whose SessionEnd was deferred and have not yet ended:"]
    for row in rows:
        sid = row[0] if not isinstance(row, dict) else row["session_id"]
        item = row[1] if not isinstance(row, dict) else row["item_id"]
        envelope = row[2] if not isinstance(row, dict) else row["envelope"]
        created = row[3] if not isinstance(row, dict) else row["created_at"]
        defer_reason = ""
        try:
            import json as _json
            data = _json.loads(envelope or "{}")
            defer_reason = data.get("defer_reason", "")
        except Exception:
            defer_reason = ""
        lines.append(
            f"- session={sid} item={item or 'n/a'} reason={defer_reason or 'unknown'} since={created}"
        )
    return "\n".join(lines) + "\n"


def remediation_with_footer(prompt_text: str) -> str:
    """Append the field-note footer to one HC's remediation prompt.

    Idempotent: re-wrapping text that already carries the footer is a
    no-op. Every FAIL / WARN remediation prompt in the Markdown report
    surfaces the footer so the operator-facing channel for the Ouroboros
    learning loop is one screen away when doctor finds work.
    """
    if _FIELD_NOTE_FOOTER in prompt_text:
        return prompt_text
    return f"{prompt_text}\n\n{_FIELD_NOTE_FOOTER}"


def _attach_remediation_footers(rec: RecordCollector) -> None:
    """Wrap each FAIL / WARN result's ``detail`` with the field-note
    footer before report rendering. Applied at the doctor result-render
    layer so per-HC modules need no edits."""
    for r in rec.results:
        if r.result in ("FAIL", "WARN"):
            r.detail = remediation_with_footer(r.detail)


def run_checks(args: DoctorArgs) -> int:
    """Run all applicable health checks and return exit code (0 or 1)."""
    conn = connect(path=args.db_path)
    rec = RecordCollector()

    for hc in HEALTH_CHECKS:
        if not _should_run_hc(hc.slug, args):
            continue
        print(f"running HC-{hc.slug}", flush=True)
        pre_len = len(rec.results)
        try:
            hc.fn(conn, args, rec)
        except Exception as exc:
            rec.record(f"HC-{hc.slug}", hc.name, "FAIL",
                       f"Internal error: {exc}")
        for new_record in rec.results[pre_len:]:
            print(f"{new_record.check_id}: {new_record.result}", flush=True)

    addendum = _render_deferred_cleanup_addendum(conn)
    conn.close()

    _attach_remediation_footers(rec)
    report = rec.format_report()
    if addendum:
        report = report + "\n" + addendum
    print(report)

    if args.file:
        out_path = Path(args.file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"\nReport saved to: {args.file}")

    return 1 if rec.fail_count > 0 else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.engines.doctor",
        description="Yoke health check engine (DB-only checks)",
    )
    parser.add_argument("--file", help="Write report to PATH")
    parser.add_argument("--fix", action="store_true", help="Attempt auto-fix where supported")
    parser.add_argument("--only", help="Comma-separated HC slug IDs to run")
    parser.add_argument("--check", dest="check_alias", help=argparse.SUPPRESS)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--quick", action="store_true",
        help="Skip GitHub-dependent HCs (no gh subprocess calls)",
    )
    scope.add_argument(
        "--full", action="store_true",
        help="Run every HC including GitHub-dependent ones (uses gh quota)",
    )
    parser.add_argument("--project", default="yoke", help="Project scope (default: yoke)")
    parser.add_argument("--db-path", help="Override DB path (testing)")
    parser.add_argument("--repo-root", help=argparse.SUPPRESS)
    parser.add_argument(
        "--list-checks",
        action="store_true",
        help="Print sorted HC slugs and exit",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit doctor.run.run JSON instead of the human Markdown report. "
            "Requires an explicit scope (--quick / --full / --only); the "
            "same gh-quota protection applies."
        ),
    )
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> Optional[DoctorArgs]:
    """Parse CLI arguments into DoctorArgs.

    Returns ``None`` when the caller asked for an information-only mode
    (e.g. ``--list-checks``) so ``main`` can exit without running checks.
    """
    parser = _build_parser()
    parsed = parser.parse_args(argv)
    if parsed.list_checks:
        for slug in sorted(hc.slug for hc in HEALTH_CHECKS):
            print(slug)
        return None
    # Force an explicit scope choice so callers can't silently run the
    # GitHub-dependent HCs (which burn gh quota). One of --quick / --full
    # / --only must be specified; --list-checks already returned above.
    only_value = parsed.only or parsed.check_alias
    if not (parsed.quick or parsed.full or only_value):
        parser.error(
            "doctor requires an explicit scope flag. Pick one:\n"
            "  --quick        skip GitHub-dependent HCs (recommended for "
            "automated polish/verify; no gh calls)\n"
            "  --full         run every HC including GitHub-dependent ones "
            "(burns gh quota; for operator-invoked /yoke doctor)\n"
            "  --only <slugs> run only the named HC(s)"
        )
    return DoctorArgs(
        file=parsed.file,
        fix=parsed.fix,
        only=only_value,
        quick=parsed.quick,
        project=parsed.project,
        db_path=parsed.db_path,
    )


def run_json(argv: Optional[Sequence[str]] = None) -> int:
    """Run Doctor through the registered ``doctor.run.run`` function id.

    Mirrors :func:`parse_args` for argument shape but routes execution
    through the dispatcher so the JSON adapter and the function call
    share one implementation. Structured handler errors still print the
    typed response envelope and exit 1 so shell callers can branch on
    success without parsing JSON. A truly unrecoverable failure (cannot
    parse args) still exits 2 like the human path.
    """
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_dispatch import dispatch

    parser = _build_parser()
    parsed = parser.parse_args(argv)
    if parsed.list_checks:
        for slug in sorted(hc.slug for hc in HEALTH_CHECKS):
            print(slug)
        return 0
    only_value = parsed.only or parsed.check_alias
    if not (parsed.quick or parsed.full or only_value):
        parser.error(
            "doctor --json requires an explicit scope flag. Pick one:\n"
            "  --quick        skip GitHub-dependent HCs\n"
            "  --full         run every HC including GitHub-dependent ones\n"
            "  --only <slugs> run only the named HC(s)"
        )

    register_all_handlers()
    payload = {
        "project": parsed.project,
        "fix": parsed.fix,
        "quick": parsed.quick,
        "full": parsed.full,
    }
    if only_value:
        payload["only"] = only_value
    if parsed.db_path:
        payload["db_path"] = parsed.db_path
    result = dispatch({
        "function": "doctor.run.run",
        "actor": {"session_id": "doctor-cli"},
        "target": {"kind": "global"},
        "intent": "doctor_cli_json",
        "payload": payload,
    })
    envelope = result.model_dump() if hasattr(result, "model_dump") else result
    print(json.dumps(envelope, default=str, indent=2))
    if envelope.get("success"):
        fail_count = envelope.get("result", {}).get("fail_count", 0)
        return 1 if fail_count > 0 else 0
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Detect --json without invoking the human-path argparse, which would
    # consume the rest of the arguments and could exit on --list-checks.
    if argv and "--json" in argv:
        return run_json(list(argv))
    args = parse_args(argv)
    if args is None:
        return 0
    return run_checks(args)


if __name__ == "__main__":
    sys.exit(main())
