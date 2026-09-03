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
  `YOKE_ENV=prod-db-admin`, before a database is created. `yoke watch pytest`,
  the generic runner, and `yoke dev run` also strip the ambient administering
  selection from their child. The fix is to use `yoke watch pytest` or point
  the run at a cluster it owns. `yoke watch doctor -- --quick` reports any
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
