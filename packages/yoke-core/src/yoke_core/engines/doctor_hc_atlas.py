"""``HC-atlas-integrity`` — hard-fact Atlas contradictions.

Enforces only contradictions the audit can prove without judgment:

* A tracker row classed ``wrapped`` is missing from
  :data:`yoke_cli.commands.registry.SUBCOMMAND_REGISTRY`.
* A wrapped CLI row maps to a function id missing from the live
  dispatcher registry.
* A registered ``yoke`` subcommand exposes no usable ``--help`` text.
* ``docs/atlas.md`` is stale relative to a freshly-rendered body.
* ``docs/function-inventory.md`` is still present AND still claims an
  empty registry while the live registry is non-empty.

Everything else lives in the audit report as data, not enforcement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_ID = "atlas-integrity"
_HC_NAME = "Atlas integrity"


def _emit_progress(stage: str) -> None:
    print(f"running HC-{_HC_ID} {stage}", flush=True)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "runtime" / "api" / "tools").is_dir():
            return parent
    return Path.cwd().resolve()


def _build_audit_report() -> dict:
    from yoke_core.tools.atlas_integrity_audit import build_report
    return build_report(_repo_root())


def _check_wrapped_tracker_in_cli(
    report: dict, fails: List[str]
) -> None:
    cli_forms = {row["cli_form"] for row in report["yoke_cli"]["rows"]}
    wrapped_rows = [
        r for r in report["operation_tracker"]["rows"] if r["status"] == "wrapped"
    ]
    missing = [r["shell_form"] for r in wrapped_rows if r["shell_form"] not in cli_forms]
    for shell_form in missing:
        fails.append(
            f"- wrapped tracker row `{shell_form}` is missing from the "
            "`yoke` subcommand registry"
        )
    if len(wrapped_rows) != report["yoke_cli"]["count"]:
        fails.append(
            "- wrapped tracker row count ({tracker}) <> yoke CLI subcommand "
            "count ({cli}); tracker classification or subcommand registry is "
            "drifting".format(
                tracker=len(wrapped_rows),
                cli=report["yoke_cli"]["count"],
            )
        )


def _check_cli_function_ids_registered(
    report: dict, fails: List[str]
) -> None:
    registry_ids = {
        row["function_id"] for row in report["function_registry"]["rows"]
    }
    missing = [
        row for row in report["yoke_cli"]["rows"]
        if row["function_id"] not in registry_ids
    ]
    for row in missing:
        fails.append(
            f"- `{row['cli_form']}` -> `{row['function_id']}` "
            "is registered as a CLI adapter but missing from the dispatcher "
            "function registry"
        )


def _check_subcommand_help_coverage(
    report: dict, fails: List[str]
) -> None:
    per = report["help_pages"]["per_subcommand"]
    for tokens, status in sorted(per.items()):
        body = (status.get("body") or "").strip()
        stderr = (status.get("stderr") or "").strip()
        if not body and not stderr:
            fails.append(
                f"- `yoke {tokens} --help` produced no usable text "
                f"(exit_code={status.get('exit_code')!r})"
            )


def _check_atlas_staleness(report: dict, fails: List[str]) -> None:
    from yoke_core.tools.atlas_render_docs import is_stale, render
    body = render(report)
    if is_stale(_repo_root(), body=body):
        fails.append(
            "- `docs/atlas.md` is stale relative to the live audit "
            "report — run `python3 -m yoke_core.tools.atlas_render_docs "
            "render` to refresh"
        )


def _check_function_inventory_replacement_state(
    report: dict, fails: List[str]
) -> None:
    path = _repo_root() / "docs" / "function-inventory.md"
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    claims_empty = (
        "Registry is reachable but empty" in text
        or "Function registry not yet wired" in text
    )
    if claims_empty and report["function_registry"]["count"] > 0:
        fails.append(
            "- `docs/function-inventory.md` still claims an empty registry, "
            f"but the live registry has {report['function_registry']['count']} "
            "entries — replace or delete the obsolete doc"
        )


def hc_atlas_integrity(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Run every Atlas hard-fact check and record one combined verdict."""
    try:
        _emit_progress("build-audit-report")
        report = _build_audit_report()
    except Exception as exc:  # pragma: no cover - audit infra failure
        rec.record(
            _HC_ID, _HC_NAME, "WARN",
            f"audit build failed: {type(exc).__name__}: {exc}",
        )
        return
    fails: List[str] = []
    _emit_progress("check-wrapped-tracker")
    _check_wrapped_tracker_in_cli(report, fails)
    _emit_progress("check-function-ids")
    _check_cli_function_ids_registered(report, fails)
    _emit_progress("check-help-coverage")
    _check_subcommand_help_coverage(report, fails)
    _emit_progress("check-doc-staleness")
    _check_atlas_staleness(report, fails)
    _emit_progress("check-function-inventory")
    _check_function_inventory_replacement_state(report, fails)
    if fails:
        rec.record(_HC_ID, _HC_NAME, "FAIL", "\n".join(fails))
    else:
        rec.record(_HC_ID, _HC_NAME, "PASS", "")


__all__ = ["hc_atlas_integrity"]
