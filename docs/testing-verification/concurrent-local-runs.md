# One cluster, many runs at once

How concurrent test invocations share a single disposable PostgreSQL
cluster without reaching each other's databases, and where a scratch
database may be created at all. Companion to
[`docs/testing-verification.md`](../testing-verification.md).

One disposable PostgreSQL cluster serves every test invocation on the
machine, and any number of them may run at once — a full three-anchor gate,
a second gate, and a raw `uv run --frozen python3 -m pytest <one file>` all
at the same time. Isolation comes from the database names rather than from a
cluster per run:

Correctness is not the same as capacity, though. *Heavy* invocations —
anything sweeping directories rather than named files — additionally queue
behind the machine-wide admission slot (`yoke_core.tools.gate_admission`), so
one heavy gate runs at a time and a queued one reports who holds the slot and
how many runs are behind it. Every wrapper-driven path arbitrates for that
slot; a bare `python3 -m pytest <dirs>` does not, which is why
`lint-raw-pytest-full-suite` denies the whole-verification-surface shape
outside the wrapper and advises on any other directory sweep. Run sweeps
through `yoke watch pytest`; file-scoped runs stay unqueued and free.
The browser and the launchd login domain are the machine's other shared resources, guarded structurally rather than per test: [`machine-shared-resources.md`](machine-shared-resources.md).

- Every database an invocation creates carries that invocation's run tag,
  minted once and published through `YOKE_TEST_RUN_TAG` so pytest-xdist
  workers share their controller's identity.
- An invocation may only ever drop databases carrying its own tag. Nothing a
  running suite does can reach another run's databases.
- Databases left behind by an interrupted run are reclaimed by an orphan
  sweep that first confirms the owning process has exited, then drops with
  `FORCE` under a bounded statement timeout.
- A run does not get to borrow an administered cluster under any spelling.
  The resolved target — explicit `YOKE_PG_DSN`, DSN file, context binding, or
  selected connection — is reduced to its host/port endpoint and compared
  with every prod-flagged local-Postgres connection this machine knows. A raw
  DSN aimed at the production SSH forward is therefore refused exactly like
  `YOKE_ENV=prod-db-admin`, before a database is created. `yoke watch pytest`
  and the generic test runner strip the ambient administering selection from
  their pytest child. `yoke dev run` deliberately preserves the caller's
  selection because it changes source resolution only; use the pytest runner
  rather than a raw source command when the child must own its database. The
  alternative is to point the run at a cluster it owns.
  `yoke watch doctor -- --quick` reports any
  existing strays with dry-run and manual removal recipes; Doctor never drops
  them. The fleet migration preflight skips the reserved `yoke_test_run`
  prefix outright so one can never be rehearsed as a tenant.

The sweep never sits in a starting suite's critical path. Cluster preparation
launches it detached and returns immediately, because dropping a database is
seconds of disk work on a loaded machine — a synchronous sweep of a large
backlog delayed pytest collection by minutes, which is the stall the cleanup
exists to prevent. One sweeper runs at a time (a lock file under the cluster
root; others skip instantly rather than queueing), and each pass stops at a
time budget, so a large backlog drains over several runs and reports how many
it deferred. Run one directly with:

```bash
yoke dev run -- python3 -m yoke_core.tools.pg_testcluster prune
```

Interrupting a run through `watch_pytest`, `run_tests`, or a QA registered
command terminates and reaps the whole process group, so xdist workers do
not outlive the run and keep its databases open. Only `SIGKILL` can bypass
that, which is what the orphan sweep backstops.

`YOKE_PG_CLUSTER_ROOT` still points an invocation at a wholly private
cluster. That is an escape hatch for a wedged shared cluster, not the normal
isolation mechanism — a full `initdb` per run would slow ordinary iteration
without adding safety the run tag does not already provide.

## The worker budget

The admission slot serialises directory sweeps, but a file-scoped run passes
it on purpose, and the sum of those is what saturates a workstation: six
lanes each running a file-scoped impacted selection at `-n 4`, plus the
`yoke` interpreters their tests shell out to, put 91 Python processes and a
load of 48 on an 18-core machine. No single run was heavy.

So whichever entry point starts a local run, it takes its worker count from
one machine-wide budget — by default one worker per core, overridden by
`YOKE_PYTEST_WORKER_BUDGET` or the machine-config `pytest_worker_budget` key.
A run takes what is free up to what it asked for and runs with that many
workers; when nothing is free it waits, naming who holds the budget; when the
one-minute load already exceeds the core count it asks for half. A pytest a
test itself spawns rides its ancestor's grant rather than queueing behind it.

The load-average halving is skipped on a GitHub-hosted Actions runner
(`GITHUB_ACTIONS=true` and `RUNNER_ENVIRONMENT=github-hosted`): that VM is
single-tenant per job, so its load average reflects only the very workers
this run started, not contention from anything else. A self-hosted runner —
a persistent host a fleet can reuse across concurrent jobs — still
arbitrates through both the load backoff and the budget, same as a local
workstation.

The budget is arbitrated the way the admission slot is — session-scoped
advisory locks on the shared test cluster, one per worker — so a crashed
run's workers return with its connection, and it fails open when no cluster
is reachable. It is a throughput guard, not a correctness gate.

## Disposable homes and orphan clusters

Before replacing `HOME` or `YOKE_MACHINE_HOME`, retain the shared test
resource environment: `YOKE_PG_CLUSTER_ROOT` and `YOKE_PG_BIN_DIR`.
`yoke dev run`, the pytest runner and candidate-bound Yoke Command QA supply
these before home
isolation. The cluster root stays independent of each run's evidence root;
`YOKE_PG_BIN_DIR` points at the machine's pinned embedded PostgreSQL binaries,
so an empty home does not select a different PostgreSQL major from PATH.
If that cache is missing, startup refuses as `postgres_binaries_unavailable`;
install with `env -u YOKE_PG_CLUSTER_ROOT -u YOKE_PG_BIN_DIR yoke local-postgres start`
in the original home, then retry. CI with an explicit service DSN needs no
local cluster or embedded cache.
For a standalone disposable home, obtain the exports in the original home:

```bash
yoke dev run -- python3 -m yoke_core.tools.pg_testcluster env
```

The output includes the root, maintenance DSN and pinned binary directory.
Apply those exports before replacing the home and pass them through unchanged. Preserve the candidate QA variables too, as described in
[source-development commands](source-development.md).

`dev run` destroys test clusters created inside its own evidence root when
the command exits, including KeyboardInterrupt and SIGTERM; captures survive.
SIGKILL cannot run exit cleanup. To reclaim clusters from older interrupted
runs without touching the shared cluster, run:

```bash
yoke dev run -- python3 -m yoke_core.tools.pg_testcluster prune-clusters
```

An older source runner that omits the shared-root handoff refuses as
`pgtest_shared_root_unbound`. Set `YOKE_PG_CLUSTER_ROOT` explicitly to the same
shared root your other test runs use, then retry; upgrade the source runner
before relying on automatic handoff.

This inventories only this user's test postmasters, verifies their pid/data
identity, and keeps the selected shared root, clusters younger than fifteen
minutes, and any cluster with a connected client. A refusal names the root
and recovery; it never removes a data directory after a failed stop.
`prune` continues to reclaim databases within the shared cluster.

`yoke local-postgres start` and `stop` manage the durable local universe.
With `YOKE_PG_CLUSTER_ROOT` set they refuse as
`local_postgres_test_cluster_override`: use the test-cluster `start`/`stop`
subcommands, or unset the variable to operate the local universe deliberately.
