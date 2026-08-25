"""Refuse a release whose migration history or schema shape is unsafe to publish.

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
optional *product-sha* only enriches the refusal.

This submits the checked-out name/digest set to the connected control plane's
semantic identity verifier, reads the receipt store, and reads the checked-out
history plus schema-shape sources. It does not accept SQL or expose ledger
digests. It does not rehearse anything, so it runs anywhere the control plane
is reachable — which is what lets it sit in a release job that could never
host the rehearsal itself.

Exits 0 when permanent packaged bytes match the live ledger and every history
entry plus this build's schema-shape digest is covered. Exits 1 when verified
evidence is unsafe (content mismatch or missing coverage). Exits 2 when
verification is unavailable (authorization, transport, unreadable response, or
an unreadable schema-shape digest) or arguments are invalid.
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


def _yoke_fleet_rehearse_command(environment: str, receipt_connection: str = "") -> str:
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
        "yoke",
        "events",
        "query",
        "--event-name",
        event_name,
        "--project",
        project,
        "--limit",
        str(_RECEIPT_QUERY_LIMIT),
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
    if not isinstance(payload, dict):
        return [], "receipt query returned a malformed envelope"
    if not payload.get("success", False):
        return [], f"receipt query refused: {payload.get('error')}"
    result_payload = payload.get("result")
    if not isinstance(result_payload, dict):
        return [], "receipt query returned a malformed result"
    rows = result_payload.get("rows")
    if not isinstance(rows, list):
        return [], "receipt query returned no rows field"
    return rows, ""


def _verify_applied_migrations(
    entries: Sequence[Dict[str, str]],
) -> Tuple[Dict[str, Any], str]:
    """Semantic content verdict, or why verification was unavailable."""
    argv = [
        "yoke",
        "migration",
        "content-identity",
        "verify",
        "--entries-json",
        json.dumps(list(entries), separators=(",", ":")),
        "--json",
    ]
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=_QUERY_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, f"{' '.join(argv[:4])} could not run: {exc}"
    if result.returncode != 0:
        details = []
        if result.stderr.strip():
            details.append(f"stderr: {result.stderr.strip()}")
        if result.stdout.strip():
            details.append(f"stdout: {result.stdout.strip()}")
        detail = "\n".join(details) or "no output"
        return {}, f"migration identity verifier exited {result.returncode}: {detail}"
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        return {}, f"migration identity verifier returned unreadable output: {exc}"
    if not isinstance(payload, dict):
        return {}, "migration identity verifier returned a malformed envelope"
    if not payload.get("success", False):
        return {}, f"migration identity verifier refused: {payload.get('error')}"
    result_payload = payload.get("result")
    if not isinstance(result_payload, dict):
        return {}, "migration identity verifier returned a malformed verdict"
    status = result_payload.get("status")
    mismatched = result_payload.get("mismatched_entries")
    verified_count = result_payload.get("verified_count")
    if (
        status not in {"verified", "mismatch"}
        or not isinstance(mismatched, list)
        or any(not isinstance(name, str) for name in mismatched)
        or not isinstance(verified_count, int)
        or isinstance(verified_count, bool)
        or (status == "verified" and mismatched)
        or (status == "mismatch" and not mismatched)
    ):
        return {}, "migration identity verifier returned a malformed verdict"
    return result_payload, ""


def _content_identity_refusal(status: Dict[str, Any]) -> str:
    detail = ", ".join(str(name) for name in status["mismatched_entries"])
    return (
        "release unsafe before tag: packaged migration content differs from "
        f"the connected applied ledger for: {detail}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2

    from yoke_core.domain import migration_preflight_receipt as receipt
    from yoke_core.domain.schema_shape_source import (
        SchemaShapeSourceError,
        digest_schema_shape,
    )
    from runtime.api.tools import yoke_migration_fleet

    environment = receipt.target_environment_for_admin_env(args[0])
    product_sha = args[1] if len(args) > 1 else ""
    project = "yoke"

    # The same reader the rehearsal uses, so a receipt and a gate can never
    # disagree about what "the history" is.
    history_entries = yoke_migration_fleet.history_entries()
    history = tuple(entry.name for entry in history_entries)
    print(f"target environment: {environment}")
    print(f"history entries carried by this build: {len(history)}")
    try:
        schema_digest = digest_schema_shape()
    except SchemaShapeSourceError as exc:
        print(
            "release verification unavailable before tag: schema-shape "
            f"digest could not be computed: {exc}",
            file=sys.stderr,
        )
        return 2
    print(f"schema-shape digest: {schema_digest}")

    candidate_entries = [
        {"name": entry.name, "content_sha256": entry.content_sha256}
        for entry in history_entries
    ]
    content_status, identity_unavailable = _verify_applied_migrations(candidate_entries)
    if identity_unavailable:
        print(
            "release verification unavailable before tag: migration content "
            f"identity could not be checked: {identity_unavailable}",
            file=sys.stderr,
        )
        return 2
    if content_status["status"] == "mismatch":
        print(_content_identity_refusal(content_status), file=sys.stderr)
        return 1
    print(
        "packaged migration content matches the connected applied ledger: "
        f"{content_status['verified_count']} verified"
    )

    rows, unreadable = _query_receipts(receipt.EVENT_NAME, project)
    if unreadable:
        print(
            "release verification unavailable before tag: fleet-preflight "
            f"receipts could not be checked: {unreadable}",
            file=sys.stderr,
        )
        return 2

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
        print(f"also {env}: {len(history) - len(missing)} of {len(history)} covered")
    if target_missing:
        receipt_env = os.environ.get("YOKE_ENV", "")
        refusal = receipt.release_refusal_message(
            environment,
            missing_by_env,
            product_sha=product_sha,
            rehearse_commands={
                env: _yoke_fleet_rehearse_command(env, receipt_env)
                for env, missing in missing_by_env.items()
                if missing
            },
            engine_wheel_source=_engine_wheel_source(product_sha),
        )
        print(f"release unsafe before tag: {refusal}", file=sys.stderr)
        return 1
    schema_missing = receipt.uncovered_schema_shape(schema_digest, rows, environment)
    if schema_missing:
        receipt_env = os.environ.get("YOKE_ENV", "")
        print(
            "release unsafe before tag: "
            + receipt.schema_shape_refusal_message(
                environment,
                schema_digest,
                product_sha=product_sha,
                rehearse_command=_yoke_fleet_rehearse_command(environment, receipt_env),
            ),
            file=sys.stderr,
        )
        return 1
    print("every history entry this build carries has been rehearsed against the fleet")
    print("this build's schema shape has been rehearsed against the fleet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
