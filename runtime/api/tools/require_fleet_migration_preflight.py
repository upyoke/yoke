"""Refuse a release whose migration history or schema shape is unsafe to publish.

Run this before the release train allocates its annotated tag: the tag is the
first irreversible act, and a release refused after it names a build that
never deployed.

Usage::

    python3 -m runtime.api.tools.require_fleet_migration_preflight \\
        --project P <target-environment> [product-sha]

Run from a checkout of the release commit. *target-environment* is the
registered name of the project environment the release is bound for — the
same name receipts are keyed by. The optional *product-sha* only enriches the
refusal.

Every migration model the project declares is checked against the fleet it
declares in the ``migration_fleet`` capability: a ``none`` fleet passes with
its reason, an undeclared fleet refuses with the declaration recipe, and any
other fleet must have this checkout's history entries and schema-shape digest
covered by that model's receipts for the target environment. For the engine's
own model the checked-out entry bytes are also submitted to the connected
control plane's semantic identity verifier. It does not accept SQL, expose
ledger digests, or rehearse anything, so it runs anywhere the control plane is
reachable — which is what lets it sit in a release job that could never host
the rehearsal itself.

Reading the declarations and coverage needs ``items.read`` on the project; a
deploy identity without it is refused with that reason, not treated as an
unrehearsed build.

Exits 0 when every model's evidence is complete, 1 when verified evidence is
unsafe (undeclared fleet, content mismatch, missing coverage), and 2 when
verification is unavailable or arguments are invalid.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from typing import Any, Dict, Optional, Sequence, Tuple

_QUERY_TIMEOUT_SECONDS = 120
_BUILD_ARTIFACTS_WORKFLOW = "yoke-build-artifacts.yml"


def _fleet_rehearse_command(
    project: str, model: str, environment: str, receipt_connection: str = ""
) -> str:
    """The fleet preflight recipe for the refusal unblock line."""
    receipt_env = receipt_connection.strip()
    receipt_env_arg = (
        shlex.quote(receipt_env) if receipt_env else "<control-plane-connection>"
    )
    return (
        f"yoke watch preflight -- --project {project} --model {model} "
        f"{environment} --record-receipt --product-sha <sha> "
        f"--receipt-env {receipt_env_arg}"
    )


def _engine_wheel_source(product_sha: str) -> str:
    sha = product_sha.strip() or "<product-sha>"
    return (
        "Ordinary pre-release rehearsal is the source tree at that commit "
        f"(no --engine-wheel); the release wheel for commit {sha} does not "
        "exist until after tag allocation. --engine-wheel pins an "
        f"already-built artifact from {_BUILD_ARTIFACTS_WORKFLOW} when you "
        "have one. The gate treats both receipts the same: coverage is "
        "history entries plus schema-shape digest of the selected engine, "
        "not packaging form."
    )


def _read_coverage(
    project: str,
    model: str,
    environments: Sequence[str],
    history: Sequence[str],
    schema_digest: str,
) -> Tuple[Dict[str, Dict[str, Any]], str, str]:
    """Each environment's own coverage, or the environment it could not read.

    One environment is read at a time because coverage is stored on the
    environment it belongs to. That is what makes "a stage receipt is not
    production evidence" a property of the store rather than a filter this
    gate has to remember to apply.
    """
    from yoke_core.domain import migration_preflight_receipt as receipt
    from yoke_core.domain.migration_preflight_receipt_store import read_coverage

    paths = receipt.coverage_paths(model, history, schema_digest)
    coverage: Dict[str, Dict[str, Any]] = {}
    for environment in environments:
        name = receipt.target_environment_for_admin_env(environment)
        values, unreadable = read_coverage(
            project=project, environment=name, paths=paths
        )
        if unreadable:
            return {}, name, unreadable
        coverage[name] = values
    return coverage, "", ""


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
    project = ""
    if "--project" in args:
        index = args.index("--project")
        project = args[index + 1] if index + 1 < len(args) else ""
        del args[index : index + 2]
    if not project or not args:
        print(
            "usage: require_fleet_migration_preflight --project P "
            "<target-environment> [product-sha]",
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain import migration_preflight_receipt as receipt
    from yoke_core.domain.migration_model_fleet_read import read_declared

    environment = receipt.target_environment_for_admin_env(args[0])
    product_sha = args[1] if len(args) > 1 else ""
    print(f"project: {project}; target environment: {environment}")
    declared, unreadable = read_declared(project)
    if unreadable:
        print(
            f"release verification unavailable before tag: {unreadable}",
            file=sys.stderr,
        )
        return 2
    if not declared.models:
        print(f"project {project} declares no migration model; nothing to verify")
        return 0
    return max(
        _verify_model(
            project, name, model, declared.fleet(name), environment, product_sha
        )
        for name, model in sorted(declared.models.items())
    )


def _verify_model(
    project: str,
    model_name: str,
    model: Dict[str, Any],
    fleet: Optional[Dict[str, Any]],
    environment: str,
    product_sha: str,
) -> int:
    """0 when this model's release evidence is complete, 1 unsafe, 2 unknown."""
    from yoke_core.domain import migration_model_fleet as fleets
    from yoke_core.domain import migration_preflight_receipt as receipt
    from yoke_core.domain import migration_preflight_refusal as refusal
    from yoke_core.domain.migration_history import HistoryError
    from yoke_core.domain.schema_shape_source import SchemaShapeSourceError

    if fleet is None:
        print(
            "release unsafe before tag: "
            + fleets.undeclared_refusal(project, model_name),
            file=sys.stderr,
        )
        return 1
    if fleet["kind"] == fleets.FLEET_NONE:
        print(f"model {model_name}: declares no live fleet ({fleet['reason']})")
        return 0
    try:
        history_entries, schema_digest = _release_inputs(model, fleet)
    except HistoryError as exc:
        print(
            f"release verification unavailable before tag: model {model_name} "
            f"history is unreadable: {exc}",
            file=sys.stderr,
        )
        return 2
    except SchemaShapeSourceError as exc:
        print(
            f"release verification unavailable before tag: model {model_name} "
            f"schema-shape digest could not be computed: {exc}",
            file=sys.stderr,
        )
        return 2
    history = tuple(entry.name for entry in history_entries)
    print(f"model {model_name}: history entries carried by this build: {len(history)}")
    print(f"schema-shape digest: {schema_digest}")
    if fleet["kind"] == fleets.FLEET_ENGINE_TENANTS:
        # Only the engine's own model is applied to the connected control
        # plane, so only its packaged bytes can be checked against that ledger.
        rc = _verify_engine_content(history_entries)
        if rc:
            return rc

    coverage, unreadable_environment, unreadable = _read_coverage(
        project, model_name, (environment,), history, schema_digest
    )
    if unreadable:
        print(
            "release verification unavailable before tag: "
            + refusal.unreadable_message(unreadable_environment, unreadable),
            file=sys.stderr,
        )
        return 2
    receipt_env = os.environ.get("YOKE_ENV", "")
    rehearse = _fleet_rehearse_command(project, model_name, environment, receipt_env)
    missing = receipt.uncovered(model_name, history, coverage[environment])
    print(
        f"covered by a passing fleet preflight: {len(history) - len(missing)} of {len(history)}"
    )
    if missing:
        message = refusal.release_refusal_message(
            environment,
            {environment: missing},
            product_sha=product_sha,
            rehearse_commands={environment: rehearse},
            engine_wheel_source=_engine_wheel_source(product_sha),
        )
        print(f"release unsafe before tag: {message}", file=sys.stderr)
        return 1
    if receipt.uncovered_schema_shape(model_name, schema_digest, coverage[environment]):
        print(
            "release unsafe before tag: "
            + refusal.schema_shape_refusal_message(
                environment,
                schema_digest,
                product_sha=product_sha,
                rehearse_command=rehearse,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        f"model {model_name}: every history entry and this build's "
        "schema shape has been rehearsed against the fleet"
    )
    return 0


def _release_inputs(
    model: Dict[str, Any], fleet: Dict[str, Any]
) -> Tuple[Tuple[Any, ...], str]:
    """The checked-out release commit's history entries and schema digest.

    Read the same way for every fleet kind: the checkout is the release.
    """
    from pathlib import Path

    from yoke_core.domain import migration_model_fleet as fleets
    from yoke_core.domain.migration_history import ordered_entries

    checkout = Path.cwd()
    modules_dir = str(model["runner"]["config"]["modules_dir"])
    entries = tuple(ordered_entries(checkout / modules_dir))
    return entries, fleets.schema_shape_digest(fleet, checkout)


def _verify_engine_content(history_entries: Sequence[Any]) -> int:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
