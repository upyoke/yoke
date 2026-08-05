"""Refuse a release carrying a migration entry no fleet preflight has covered.

Run this before the release train allocates its annotated tag. The tag is the
first irreversible act, and a release refused after it leaves a tag naming a
build that never deployed — which has happened, and which cleaning up costs
more than the check does.

Usage::

    python3 -m runtime.api.tools.require_fleet_migration_preflight \\
        <target-environment> [product-sha]

*target-environment* is the environment the release is bound for (``stage`` or
``production``); an admin connection name is accepted and normalized. The
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
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Far above any plausible receipt count. Truncation can only hide coverage,
#: never invent it, so the worst a too-small bound produces is a refusal that
#: names the entries and the command to clear them.
_RECEIPT_QUERY_LIMIT = 500
_QUERY_TIMEOUT_SECONDS = 120


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

    from yoke_core.domain import migration_fleet_preflight
    from yoke_core.domain import migration_preflight_receipt as receipt

    environment = args[0]
    product_sha = args[1] if len(args) > 1 else ""
    project = "yoke"

    # The same reader the rehearsal uses, so a receipt and a gate can never
    # disagree about what "the history" is.
    history = migration_fleet_preflight.history_names()
    print(f"target environment: {receipt.target_environment_for_admin_env(environment)}")
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
            receipt.refusal_message(environment, missing, product_sha=product_sha),
            file=sys.stderr,
        )
        return 1
    print("every history entry this build carries has been rehearsed against the fleet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
