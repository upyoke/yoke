"""Refuse a release whose migration history is unsafe to publish.

Run this before the release train allocates its annotated tag. The tag is the
first irreversible act, and a release refused after it leaves a tag naming a
build that never deployed — which has happened, and which cleaning up costs
more than the check does.

Usage::

    python3 -m runtime.api.tools.require_fleet_migration_preflight \\
        <target-environment> [product-sha]

*target-environment* is the registered name of the environment the release is
bound for (``stage`` / ``prod``) — the same name receipts are keyed by, which
the release train resolves from the deployment run's typed environment
reference. An admin connection name is also accepted and normalized. The
optional *product-sha* only enriches the refusal, since coverage is a question
about history entries rather than about which commit carries them.

This reads the connected control plane's applied ledger, the receipt store,
and the checked-out history. It does not rehearse anything, so it runs
anywhere the control plane is reachable — which is what lets it sit in a
release job that could never host the rehearsal itself.

Exits 0 when permanent packaged bytes match the live ledger and every entry is
covered. Exits 1 on a content mismatch, missing coverage, or an unreadable
ledger or receipt query.
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
_BUILD_ARTIFACTS_WORKFLOW = "yoke-build-artifacts.yml"
_LEDGER_QUERY = (
    "SELECT migration_name, content_sha256 "
    "FROM applied_migrations ORDER BY migration_name"
)


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
        f"{admin_env} --engine-wheel <yoke_core-wheel-from-yoke-build-artifacts> "
        "--record-receipt --product-sha <sha> "
        f"--receipt-env {receipt_env_arg}"
    )


def _engine_wheel_source(product_sha: str) -> str:
    sha = product_sha.strip() or "<product-sha>"
    return (
        "The engine wheel is the yoke_core wheel produced by "
        f"{_BUILD_ARTIFACTS_WORKFLOW} for commit {sha} "
        "(yoke-release.yml calls that factory). Take that wheel artifact "
        "from the factory run for this SHA and pass it to --engine-wheel."
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


def _query_applied_migrations() -> Tuple[List[Tuple[Any, Any]], str]:
    """Applied migration content rows, or why they could not be read."""
    argv = ["yoke", "db", "read", _LEDGER_QUERY, "--json"]
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
        return [], f"applied migration query exited {result.returncode}: {detail}"
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        return [], f"applied migration query returned unreadable output: {exc}"
    if not payload.get("success", False):
        return [], f"applied migration query refused: {payload.get('error')}"
    result_payload = payload.get("result", {})
    if result_payload.get("truncated"):
        return [], "applied migration query was truncated"
    columns = result_payload.get("columns")
    if columns != ["migration_name", "content_sha256"]:
        return [], f"applied migration query returned unexpected columns: {columns!r}"
    rows = result_payload.get("rows")
    if not isinstance(rows, list) or any(
        not isinstance(row, list) or len(row) != 2 for row in rows
    ):
        return [], "applied migration query returned malformed rows"
    return [(row[0], row[1]) for row in rows], ""


def _content_identity_refusal(status: Any) -> str:
    detail = "; ".join(
        f"{item.entry_name}: ledger={item.recorded_sha256} "
        f"packaged={item.packaged_sha256}"
        for item in status.mismatches
    )
    return (
        "release refused before tag: packaged migration content differs from "
        f"the connected applied ledger: {detail}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2

    from yoke_core.domain import migration_preflight_receipt as receipt
    from yoke_core.domain.migration_content_identity import (
        compare_content_identities,
    )
    from runtime.api.tools import yoke_migration_fleet

    environment = receipt.target_environment_for_admin_env(args[0])
    product_sha = args[1] if len(args) > 1 else ""
    project = "yoke"

    # The same reader the rehearsal uses, so a receipt and a gate can never
    # disagree about what "the history" is.
    history = yoke_migration_fleet.history_names()
    print(f"target environment: {environment}")
    print(f"history entries carried by this build: {len(history)}")

    ledger_rows, ledger_unreadable = _query_applied_migrations()
    if ledger_unreadable:
        print(
            "release refused before tag: the connected applied migration "
            f"ledger could not be read: {ledger_unreadable}",
            file=sys.stderr,
        )
        return 1
    content_status = compare_content_identities(
        yoke_migration_fleet.history_entries(), ledger_rows
    )
    if content_status.mismatches:
        print(_content_identity_refusal(content_status), file=sys.stderr)
        return 1
    print(
        "packaged migration content matches the connected applied ledger: "
        f"{len(content_status.verified)} verified"
    )

    rows, unreadable = _query_receipts(receipt.EVENT_NAME, project)
    if unreadable:
        print(receipt.unreadable_message(environment, unreadable), file=sys.stderr)
        return 1

    missing_by_env = receipt.coverage_by_environment(
        history, rows, receipt.RELEASE_ENVIRONMENTS
    )
    if environment not in missing_by_env:
        missing_by_env[environment] = receipt.uncovered(history, rows, environment)
    target_missing = missing_by_env[environment]
    covered = len(history) - len(target_missing)
    print(f"covered by a passing fleet preflight: {covered} of {len(history)}")
    for env, missing in missing_by_env.items():
        if env == environment:
            continue
        print(
            f"also {env}: "
            f"{len(history) - len(missing)} of {len(history)} covered"
        )
    if target_missing:
        receipt_env = os.environ.get("YOKE_ENV", "")
        print(
            receipt.release_refusal_message(
                environment,
                missing_by_env,
                product_sha=product_sha,
                rehearse_commands={
                    env: _yoke_fleet_rehearse_command(env, receipt_env)
                    for env, missing in missing_by_env.items()
                    if missing
                },
                engine_wheel_source=_engine_wheel_source(product_sha),
            ),
            file=sys.stderr,
        )
        return 1
    print("every history entry this build carries has been rehearsed against the fleet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
