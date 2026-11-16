"""Start the native disposable test Postgres for one yoke-suite shard.

Linux CI runs Postgres in a container (``yoke-test-runner``). The yoke-suite
workflow's Windows and macOS shards have no container runtime, so they run
the product's own pinned engine instead: fetch the embedded binaries the way
``yoke local-postgres start`` does, start the disposable test cluster
(:mod:`yoke_core.tools.pg_testcluster`) under the runner's temp directory,
and hand its connection to every later step through ``$GITHUB_ENV``. The
suite's conftests then find an explicit DSN and never start a cluster of
their own from inside an xdist worker.

    python -m yoke_core.tools.ci_suite_postgres start
    python -m yoke_core.tools.ci_suite_postgres stop
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.domain import postgres_binaries

CLUSTER_ROOT_ENV = "YOKE_PG_CLUSTER_ROOT"
DSN_ENV = "YOKE_PG_DSN"


def _refuse(reason: str, recovery: str) -> int:
    print(f"{reason}. Recovery: {recovery}.", file=sys.stderr, flush=True)
    return 1


def cluster_root() -> Path:
    """The run-scoped cluster directory under the runner's temp directory."""
    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    if not runner_temp:
        raise SystemExit(
            "ci_suite_postgres_outside_actions: RUNNER_TEMP is unset. Recovery: "
            "run this inside a GitHub Actions job, or start a local cluster with "
            "`yoke dev run -- python3 -m yoke_core.tools.pg_testcluster start`."
        )
    return Path(runner_temp) / "yoke-pg"


def start() -> int:
    """Fetch the engine, start the cluster and export its connection."""
    destination = os.environ.get("GITHUB_ENV", "").strip()
    if not destination:
        return _refuse(
            "ci_suite_postgres_no_github_env: GITHUB_ENV is unset, so later steps "
            "could not reach the cluster",
            "run this inside a GitHub Actions job",
        )
    bin_dir = postgres_binaries.ensure_binaries(emit=lambda line: print(line, flush=True))
    os.environ[postgres_binaries.BIN_DIR_ENV] = str(bin_dir)
    os.environ[CLUSTER_ROOT_ENV] = str(cluster_root())

    from yoke_core.tools import pg_testcluster

    rc = pg_testcluster.ensure_started()
    if rc != 0:
        return _refuse(
            f"ci_suite_postgres_start_failed: the disposable cluster under "
            f"{cluster_root()} exited {rc}",
            "read the initdb and server log lines above, then rerun the job",
        )
    exports = {
        postgres_binaries.BIN_DIR_ENV: str(bin_dir),
        CLUSTER_ROOT_ENV: str(cluster_root()),
        DSN_ENV: pg_testcluster.dsn(),
    }
    with Path(destination).open("a", encoding="utf-8") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in exports.items()))
    print(f"native test Postgres ready: {exports[DSN_ENV]}", flush=True)
    return 0


def stop() -> int:
    """Stop the cluster the start step left running."""
    os.environ.setdefault(CLUSTER_ROOT_ENV, str(cluster_root()))
    from yoke_core.tools import pg_testcluster

    return pg_testcluster.stop()


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    commands = {"start": start, "stop": stop}
    if len(args) != 1 or args[0] not in commands:
        print("usage: python -m yoke_core.tools.ci_suite_postgres {start|stop}", file=sys.stderr)
        return 2
    return commands[args[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
