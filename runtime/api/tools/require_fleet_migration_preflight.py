"""Refuse a release carrying a migration entry no fleet preflight has covered.

Run this before the release train allocates its annotated tag. The tag is the
first irreversible act, and a release refused after it leaves a tag naming a
build that never deployed — which has happened, and which cleaning up costs
more than the check does.

Usage::

    python3 -m runtime.api.tools.require_fleet_migration_preflight \\
        <target-environment> [product-sha]

*target-environment* is the environment the release is bound for. The release
train dispatches this job with its own hosted-target vocabulary (``stage`` or
``production``); this tool sits on that boundary and translates the train's
label to the registered environment name receipts are keyed by (``stage`` /
``prod``). An admin connection name is also accepted and normalized. The
optional *product-sha* only enriches the refusal, since coverage is a question
about history entries rather than about which commit carries them.

This reads the receipt store and the checked-out history. It does not rehearse
anything, so it runs anywhere the control plane is reachable — which is what
lets it sit in a release job that could never host the rehearsal itself.

Exits 0 when every entry is covered, 1 when any is not or when the receipts
could not be read.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Far above any plausible receipt count. Truncation can only hide coverage,
#: never invent it, so the worst a too-small bound produces is a refusal that
#: names the entries and the command to clear them.
_RECEIPT_QUERY_LIMIT = 500
_QUERY_TIMEOUT_SECONDS = 120

#: Platform's promotion train names hosted targets ``stage``/``production``,
#: an input contract this tool cannot rename; environment registry names are
#: ``stage``/``prod``. Translate at this boundary only — everything behind it
#: speaks environment names.
_TRAIN_ENVIRONMENT_NAMES = {"production": "prod", "staging": "stage"}


def _environment_name(environment: str) -> str:
    """Registered environment name for a train label or admin connection."""
    from yoke_core.domain import migration_preflight_receipt as receipt

    name = receipt.target_environment_for_admin_env(environment)
    return _TRAIN_ENVIRONMENT_NAMES.get(name, name)


def _yoke_fleet_rehearse_command(
    environment: str, receipt_connection: str = ""
) -> str:
    """Yoke source-dev fleet adapter recipe for the refusal unblock line."""
    from yoke_core.domain import migration_preflight_receipt as receipt

    admin_env = receipt.admin_connection_for_environment(environment)
    receipt_env = receipt_connection.strip()
    receipt_env_arg = (
        shlex.quote(receipt_env) if receipt_env else "<control-plane-connection>"
    )
    return (
        "yoke watch preflight -- "
        f"{admin_env} --record-receipt --product-sha <sha> "
        f"--receipt-env {receipt_env_arg}"
    )


def _query_receipts(event_name: str, project: str) -> Tuple[List[Dict[str, Any]], str]:
    """Receipt rows, or the reason they could not be read."""
    argv = [
        "yoke", "events", "query",
        "--event-name", event_name,
        "--project", project,
        "--limit", str(_RECEIPT_QUERY_LIMIT),
        "--json",
    ]
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=_QUERY_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"{' '.join(argv[:3])} could not run: {exc}"
    if result.returncode != 0:
        details = []
        if result.stderr.strip():
            details.append(f"stderr: {result.stderr.strip()}")
        if result.stdout.strip():
            details.append(f"stdout: {result.stdout.strip()}")
        detail = "\n".join(details) or "no output"
        return [], f"receipt query exited {result.returncode}: {detail}"
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        return [], f"receipt query returned unreadable output: {exc}"
    if not payload.get("success", False):
        return [], f"receipt query refused: {payload.get('error')}"
    rows = payload.get("result", {}).get("rows")
    if not isinstance(rows, list):
        return [], "receipt query returned no rows field"
    return rows, ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2

    from yoke_core.domain import migration_preflight_receipt as receipt
    from runtime.api.tools import yoke_migration_fleet

    environment = _environment_name(args[0])
    product_sha = args[1] if len(args) > 1 else ""
    project = "yoke"

    # The same reader the rehearsal uses, so a receipt and a gate can never
    # disagree about what "the history" is.
    history = yoke_migration_fleet.history_names()
    print(f"target environment: {environment}")
    print(f"history entries carried by this build: {len(history)}")

    rows, unreadable = _query_receipts(receipt.EVENT_NAME, project)
    if unreadable:
        print(receipt.unreadable_message(environment, unreadable), file=sys.stderr)
        return 1

    missing = receipt.uncovered(history, rows, environment)
    covered = len(history) - len(missing)
    print(f"covered by a passing fleet preflight: {covered} of {len(history)}")
    if missing:
        print(
            receipt.refusal_message(
                environment,
                missing,
                product_sha=product_sha,
                rehearse_command=_yoke_fleet_rehearse_command(
                    environment, os.environ.get("YOKE_ENV", "")
                ),
            ),
            file=sys.stderr,
        )
        return 1
    print("every history entry this build carries has been rehearsed against the fleet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
