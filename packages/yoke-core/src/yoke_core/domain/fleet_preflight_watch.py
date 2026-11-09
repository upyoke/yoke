"""Fleet preflight output classification and watched execution."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Sequence
from yoke_core.domain.watch_throttle import Classification, LineClass

KIND = "preflight"



PREFLIGHT_MODULE = "yoke_core.tools.preflight_fleet_migrations"



PREFLIGHT_URGENT_RE = re.compile(
    r"(^FAIL\b|could not (?:copy|read)\b|receipt was not recorded\b"
    r"|release gate will still refuse\b|^Traceback \(most recent call last\):"
    r"|^(?:[\w.]*Error|[\w.]*Exception):|^fatal:)",
    re.IGNORECASE,
)



PREFLIGHT_SUMMARY_RE = re.compile(
    r"(^\d+ passed,\s+\d+ failed(?:,\s+\d+ skipped)?\b"
    r"|^skipped \S+ -- |^receipt recorded\b)",
    re.IGNORECASE,
)



PREFLIGHT_PROGRESS_RE = re.compile(
    r"(^PASS\b|^scratch databases skipped\b|^fleet roster:"
    r"|^\s*(?:member|not a member)\s"
    r"|^engine artifact:|^environment:|^rehearsal cluster:"
    r"|^instant-(?:copy|census)\b|^diagnostic instant census:"
    r"|^\s*(?:copy(?:ing)?|converg(?:e|ing))\b)",
    re.IGNORECASE,
)



PREFLIGHT_PROGRESS_PATTERN = re.compile(
    "|".join(
        (
            PREFLIGHT_URGENT_RE.pattern,
            PREFLIGHT_SUMMARY_RE.pattern,
            PREFLIGHT_PROGRESS_RE.pattern,
        )
    ),
    re.IGNORECASE,
)



def _timing_outcome_failed(line: str) -> bool:
    """True when a deployment-start timing line records outcome failed."""
    payload = line.removeprefix("Deployment start timing: ").strip()
    try:
        record = json.loads(payload)
    except json.JSONDecodeError:
        return False
    return isinstance(record, dict) and record.get("outcome") == "failed"



def classify_preflight_line(line: str) -> Classification:
    """Classify one fleet-preflight output line."""
    if line.startswith("Deployment start timing: "):
        if _timing_outcome_failed(line):
            return Classification(LineClass.URGENT)
        return Classification(LineClass.METADATA)
    if PREFLIGHT_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if PREFLIGHT_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if PREFLIGHT_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    return Classification(LineClass.NOISE)



def _preflight_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying project preflight invocation."""
    return [sys.executable, "-m", PREFLIGHT_MODULE, *list(args)]



def preflight_failure(rc: int, raw_capture: Path) -> str:
    """Keep launch/import failures actionable in both watcher captures."""
    if rc == 0:
        return ""
    try:
        output = raw_capture.read_text(errors="replace")
    except OSError:
        output = ""
    reason = (
        "fleet_preflight_import_failed"
        if "ModuleNotFoundError:" in output or "ImportError:" in output
        else "fleet_preflight_failed"
    )
    return (
        f"{reason}: exit code {rc}; diagnostic capture: {raw_capture}. "
        "Read the capture and correct its named cause, then retry "
        "yoke watch preflight with the same arguments. For a missing packaged "
        "module, reinstall a complete Yoke release with yoke update, or report "
        "the capture to the control-plane operator if that release is defective."
    )



def run_preflight(args: Sequence[str]) -> int:
    """Run the fleet rehearsal under the standard capture contract."""
    from yoke_core.domain.watch_capture_binding import mint_cli_capture_paths, stamp_writer
    from yoke_core.domain.watch_runner import run_watcher
    raw, progress = mint_cli_capture_paths(KIND)
    stamp_writer(progress, KIND)
    return run_watcher(
        argv=_preflight_argv(args), classifier=classify_preflight_line,
        raw_capture=raw, progress_capture=progress, kind=KIND,
        exit_metadata=lambda rc: preflight_failure(rc, raw),
    )
