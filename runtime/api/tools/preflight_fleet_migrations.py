"""Rehearse the pending migration history against every live tenant database.

Run this before releasing a build that carries an unapplied history entry. It
answers the only question that matters about such an entry — does it still
apply to the databases that are behind? — by running it against a copy of
each of them, on the local embedded cluster, exactly as a booting container
would. The live databases are only read.

Usage::

    yoke watch preflight -- <env-name> [db ...]
        [--engine-wheel PATH]
        [--record-receipt [--product-sha SHA] [--receipt-env NAME]]

    yoke watch preflight -- prod-db-admin --record-receipt --receipt-env prod
    yoke watch preflight -- stage-db-admin --record-receipt --receipt-env prod

where *env-name* is a configured admin connection (``prod-db-admin`` or
``stage-db-admin``). Naming databases limits the run to those; the default is
every tenant database on that cluster.

``--record-receipt`` records the pass in the control plane, which is what the
release gate reads before allocating a tag.
Receipts always target the prod control plane. The selected admin connection
changes the covered fleet, not the receipt plane. ``--receipt-env`` names that
control plane explicitly. Receipts are recorded only on passing runs, so they
cannot exist for fleets this did not clear.

``--engine-wheel`` puts the named release artifact at the head of the import
path before any ``yoke_core`` module loads. The preflight refuses a prior core
import or an origin outside that wheel, so a selected artifact can never fall
back to the ambient checkout. Its filename, digest, and schema member are
printed and included in any recorded receipt.

The watcher keeps output unbuffered, streams the per-database verdicts and
receipt, writes the sentinel consumed by ``yoke watch tail``, and preserves
the preflight exit code. Exits non-zero when any database fails, so a release
step can gate on it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple

from runtime.api.tools.preflight_engine_artifact import (
    EngineArtifactError,
    activate_engine_artifact as _activate_engine_artifact,
)
from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema import (
    connection_is_prod,
    same_universe_https_env,
)

_RECEIPT_TIMEOUT_SECONDS = 120


def _split_flags(args: List[str]) -> Tuple[List[str], bool, str, str, str]:
    """Separate the receipt flags from the environment and database operands."""
    positional: List[str] = []
    record = False
    product_sha = ""
    receipt_env = ""
    engine_wheel = ""
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--record-receipt":
            record = True
        elif token in {"--product-sha", "--receipt-env", "--engine-wheel"}:
            flag = token
            index += 1
            if index >= len(args):
                raise ValueError(f"{flag} requires a value")
            if flag == "--product-sha":
                product_sha = args[index]
            elif flag == "--receipt-env":
                receipt_env = args[index]
            else:
                engine_wheel = args[index]
        else:
            positional.append(token)
        index += 1
    return positional, record, product_sha, receipt_env, engine_wheel


def _release_gate_receipt_env() -> str:
    """Return the configured product connection owning release evidence."""
    config = machine_config.load_config()
    connections = config.get("connections")
    if not isinstance(connections, Mapping):
        return ""
    authorities = {
        same_universe_https_env(config, str(env)) or str(env)
        for env, connection in connections.items()
        if isinstance(connection, Mapping) and connection_is_prod(connection)
    }
    return next(iter(authorities)) if len(authorities) == 1 else ""


def _record_receipt(
    *,
    receipt_env: str,
    environment: str,
    product_sha: str,
    entries: Sequence[str],
    engine_artifact: Mapping[str, str],
) -> str:
    """Write the pass to the control plane; return a reason on failure."""
    from yoke_core.domain import migration_preflight_receipt as receipt

    context = receipt.receipt_context(
        environment,
        product_sha,
        entries,
        engine_artifact=engine_artifact,
    )
    argv = [
        "yoke",
        "events",
        "emit",
        "--name",
        receipt.EVENT_NAME,
        "--kind",
        receipt.EVENT_KIND,
        "--type",
        receipt.EVENT_TYPE,
        "--source-type",
        receipt.SOURCE_TYPE,
        "--project",
        "yoke",
        "--context",
        json.dumps(context),
    ]
    # The receipt belongs to the control plane the release gate will read, not
    # the separately selected admin cluster, so the child gets its own env.
    child_env = dict(os.environ, YOKE_ENV=receipt_env)
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_RECEIPT_TIMEOUT_SECONDS,
            env=child_env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run: {exc}"
    if result.returncode != 0:
        return f"exited {result.returncode}: {(result.stderr or '').strip()}"
    return ""


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2

    try:
        positional, record, product_sha, receipt_env, engine_wheel = _split_flags(args)
        engine_artifact = _activate_engine_artifact(engine_wheel)
    except (EngineArtifactError, ValueError) as exc:
        print(f"engine artifact selection failed: {exc}", file=sys.stderr)
        return 2
    if not positional:
        print("name the admin connection to rehearse against", file=sys.stderr)
        return 2
    # Read before selecting admin readiness so the receipt remains explicitly
    # bound to the caller's control plane rather than the admin cluster.
    receipt_env = receipt_env or os.environ.get("YOKE_ENV", "")
    if record and not receipt_env:
        print(
            "--record-receipt needs a control-plane connection to write to, and "
            "YOKE_ENV is unset. Name one with --receipt-env.",
            file=sys.stderr,
        )
        return 2
    if record:
        release_gate_env = _release_gate_receipt_env()
        if not release_gate_env:
            print(
                "--record-receipt could not resolve one prod release-gate "
                "authority from the configured connections; mark the owning "
                "connection with prod=true.",
                file=sys.stderr,
            )
            return 2
        if receipt_env != release_gate_env:
            print(
                "--record-receipt must write to the prod release-gate control "
                f"plane. Retry: yoke watch preflight -- {positional[0]} "
                "[db ...] --record-receipt --product-sha <sha> "
                f"--receipt-env {release_gate_env}",
                file=sys.stderr,
            )
            return 2

    from yoke_core.domain import local_universe, migration_fleet_preflight
    from yoke_core.domain.connected_env_readiness import activate_selected_postgres
    from yoke_core.tools.yoke_migration_fleet import database_dsn
    from runtime.api.tools import yoke_migration_fleet

    print(f"engine artifact: {engine_artifact.display()}")
    authority = activate_selected_postgres(positional[0])

    spec = local_universe.cluster_spec(
        bin_dir=local_universe.ensure_engine_binaries(lambda msg: print(f"  {msg}"))
    )

    def dsn_for(database: str) -> str:
        return database_dsn(authority.dsn, database)

    databases = positional[1:] or yoke_migration_fleet.tenant_databases(dsn_for)
    plan = yoke_migration_fleet.rehearsal_plan()
    print(f"environment: {positional[0]}")
    print(f"rehearsal cluster: {spec.sock_dir}")

    with tempfile.TemporaryDirectory(prefix="yoke-migration-rehearsal-") as work:
        verdicts = migration_fleet_preflight.rehearse_fleet(
            dsn_for,
            databases=databases,
            plan=plan,
            spec=spec,
            work_dir=Path(work),
            emit=print,
        )

    failed = [v for v in verdicts if not v.passed]
    print(f"\n{len(verdicts) - len(failed)} passed, {len(failed)} failed")
    if failed or not record:
        return 1 if failed else 0

    entries = plan.history
    unwritten = _record_receipt(
        receipt_env=receipt_env,
        environment=positional[0],
        product_sha=product_sha,
        entries=entries,
        engine_artifact=engine_artifact.evidence(),
    )
    if unwritten:
        # A pass nobody recorded reads to the operator as an unblocked release
        # and to the gate as an unrehearsed one. Failing here is what keeps
        # those two from disagreeing.
        print(
            f"fleet rehearsal passed but its receipt was not recorded on "
            f"{receipt_env}, so the release gate will still refuse: {unwritten}",
            file=sys.stderr,
        )
        return 1
    print(f"receipt recorded on {receipt_env} covering {len(entries)} history entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
