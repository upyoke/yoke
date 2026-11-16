"""Stop a release bridge that a newer dispatch has replaced, before its tag.

GitHub can hold a dispatched bridge queued for hours and refuse to cancel it.
The deploy driver then re-drives the stage with ``--fresh``, which dispatches
a new bridge under a new intent in the same deploy stage scope. Nothing stops
the stuck run from starting later and releasing beside its replacement, so
right before the tag — the first irreversible act — the bridge asks the
control plane whether its own ``yoke_dispatch_id`` is still the newest intent
for its stage. Replaced: it writes ``current=false`` and exits cleanly with a
named notice, and every later step is skipped. Platform promotion is only ever
dispatched by the bridge after this gate.

A control plane that predates the read cannot answer; the bridge proceeds
with a warning, as every bridge did before the read existed. Any other
refusal fails the bridge, which has not yet tagged or dispatched anything.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

UNAVAILABLE = 2
_TIMEOUT_SECONDS = 120
_UNSERVED_CODES = frozenset({"function_version_skew", "function_not_registered"})


def _read(project: str, correlation_id: str) -> Tuple[int, str, str]:
    try:
        completed = subprocess.run(
            [
                "yoke",
                "github-actions",
                "dispatch-intent",
                "current",
                correlation_id,
                "--project",
                project,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", f"dispatch currency read did not complete: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def decide(correlation_id: str, code: int, stdout: str, stderr: str) -> Tuple[int, bool, str]:
    """Exit code, whether the bridge is current, and the line to print."""
    detail = " | ".join(t.strip() for t in (stderr, stdout) if t.strip()) or "no output"
    try:
        payload = json.loads(stdout)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return UNAVAILABLE, False, (
            f"::error title=dispatch_currency_unread::{detail}. Re-run the "
            "bridge once the control plane answers; nothing is tagged yet."
        )
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    if code != 0 or not payload.get("success"):
        if str(error.get("code") or "") in _UNSERVED_CODES:
            return 0, True, (
                "::warning title=dispatch_currency_unserved::The control plane "
                "predates the dispatch currency read, so this bridge proceeds "
                f"unchecked: {detail}"
            )
        return UNAVAILABLE, False, (
            f"::error title=dispatch_currency_refused::{detail}. Fix the named "
            "cause and re-run the bridge; nothing is tagged yet."
        )
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if not result.get("found"):
        return UNAVAILABLE, False, (
            "::error title=dispatch_intent_unknown::No Yoke dispatch intent "
            f"records yoke_dispatch_id {correlation_id}. Release only through "
            "a deployment run: `yoke --env <plane> watch deploy -- <RUN> "
            "--from-stage <STAGE> --fresh`."
        )
    if result.get("current"):
        return 0, True, (
            f"Dispatch {correlation_id} is the newest intent for "
            f"{result.get('scope')}; releasing."
        )
    newest_run = result.get("newest_run_id") or "not yet started"
    return 0, False, (
        "::notice title=bridge_superseded::Dispatch "
        f"{correlation_id} was replaced by {result.get('newest_correlation_id')} "
        f"(run {newest_run}) for {result.get('scope')}; this bridge exits "
        "before its tag and releases nothing."
    )


def _write_output(current: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"current={'true' if current else 'false'}\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="Project that dispatched this run.")
    parser.add_argument("--dispatch-id", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    code, current, line = decide(args.dispatch_id, *_read(args.project, args.dispatch_id))
    print(line, file=sys.stderr if code else sys.stdout)
    if code == 0:
        _write_output(current)
    return code


if __name__ == "__main__":
    sys.exit(main())


__all__: List[str] = ["UNAVAILABLE", "decide", "main"]
