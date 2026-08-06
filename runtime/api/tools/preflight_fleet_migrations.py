"""Rehearse the pending migration history against every live tenant database.

Run this before releasing a build that carries an unapplied history entry. It
answers the only question that matters about such an entry — does it still
apply to the databases that are behind? — by running it against a copy of
each of them, on the local embedded cluster, exactly as a booting container
would. The live databases are only read.

Usage::

    python3 -m runtime.api.tools.preflight_fleet_migrations <env-name> [db ...]
        [--record-receipt [--product-sha SHA] [--receipt-env NAME]]

where *env-name* is a configured admin connection (``prod-db-admin`` or
``stage-db-admin``). Naming databases limits the run to those; the default is
every tenant database on that cluster.

``--record-receipt`` records the pass in the control plane, which is what the
release gate reads before allocating a tag. The receipt is written through the
ambient ``YOKE_ENV`` connection as it stood before this run repointed it at the
admin cluster; ``--receipt-env`` names it explicitly instead. It is recorded
only on a passing run, so a receipt cannot exist for a fleet this did not
clear.

Exits non-zero when any database fails, so a release step can gate on it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

_RECEIPT_TIMEOUT_SECONDS = 120


def _split_flags(args: List[str]) -> Tuple[List[str], bool, str, str]:
    """Separate the receipt flags from the environment and database operands."""
    positional: List[str] = []
    record = False
    product_sha = ""
    receipt_env = ""
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--record-receipt":
            record = True
        elif token == "--product-sha":
            index += 1
            product_sha = args[index] if index < len(args) else ""
        elif token == "--receipt-env":
            index += 1
            receipt_env = args[index] if index < len(args) else ""
        else:
            positional.append(token)
        index += 1
    return positional, record, product_sha, receipt_env


def _record_receipt(
    *, receipt_env: str, environment: str, product_sha: str, entries: Sequence[str]
) -> str:
    """Write the pass to the control plane; return a reason on failure."""
    from yoke_core.domain import migration_preflight_receipt as receipt

    context = receipt.receipt_context(environment, product_sha, entries)
    argv = [
        "yoke", "events", "emit",
        "--name", receipt.EVENT_NAME,
        "--kind", receipt.EVENT_KIND,
        "--type", receipt.EVENT_TYPE,
        "--source-type", receipt.SOURCE_TYPE,
        "--project", "yoke",
        "--context", json.dumps(context),
    ]
    # The rehearsal repointed YOKE_ENV at the admin cluster it dumps from. The
    # receipt belongs to the control plane the release gate will read, which is
    # a different connection, so the child gets its own.
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

    positional, record, product_sha, receipt_env = _split_flags(args)
    if not positional:
        print("name the admin connection to rehearse against", file=sys.stderr)
        return 2
    # Read before the rehearsal repoints it, so the receipt lands on the
    # connection the caller was already using rather than the admin cluster.
    receipt_env = receipt_env or os.environ.get("YOKE_ENV", "")
    if record and not receipt_env:
        print(
            "--record-receipt needs a control-plane connection to write to, and "
            "YOKE_ENV is unset. Name one with --receipt-env.",
            file=sys.stderr,
        )
        return 2

    os.environ["YOKE_ENV"] = positional[0]
    from yoke_core.domain import db_backend, local_universe, migration_fleet_preflight
    from runtime.api.tools import yoke_migration_fleet

    spec = local_universe.cluster_spec(
        bin_dir=local_universe.ensure_engine_binaries(lambda msg: print(f"  {msg}"))
    )

    def dsn_for(database: str) -> str:
        return db_backend.resolve_pg_dsn(dbname=database)

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
        )

    for verdict in verdicts:
        print(verdict.line)
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
