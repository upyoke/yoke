# Doctor — Claim, Run and Release

## 0. Exclusive process authority

```sh
yoke sessions touch --mode doctor
yoke claims work acquire --process DOCTOR --project {project} --reason doctor_run --json
```

Retain `claim_id`. On `claim_conflict`, stop before running the engine or
producing a report: another Doctor owns the process; wait for it or end that
holder first.

Every post-acquisition exit releases the DOCTOR claim, including read-only
and failing runs. An early stop uses:

```sh
yoke claims work release --claim-id {claim_id} --reason doctor_stop --json
```

## 1. Execute one explicit scope

```sh
yoke watch doctor -- --full --project {project} [--file {path}] [--fix]
```

Operator-invoked Doctor uses `--full`, including GitHub reconciliation.
Automated verification may use `--quick` when those checks do not matter;
`--only <slug[,slug...]>` selects named checks. Scope is mandatory; no flag
exits 2. Project comes from the explicit argument, YOKE_PROJECT or checkout
binding; without one, `project_required` names `--project P` and accessible
projects. There is no seeded-self fallback.

The watcher owns capture/progress and preserves exit status. HTTPS composes
bounded server checks with local source checks; local Postgres runs in process.
Continue a yielded handle to exit. Keep the exit code and full report.

## 2. Display and repair

Show summary, failures, warnings, passes and N/A with reasons/count.
Without `--fix`, proceed to release. Read [notes.md](notes.md) before repair;
a long-stale installation needs a read-only pass and acceptable mutation-volume
confirmation before bulk `--fix`.

The engine repairs bidirectional GitHub drift (orphan reconciliation, titles,
bodies, labels, state and frozen/blocked/task drift), wrong-repo issues when
the project's verified binding moved, and orphaned scratch files/directories.
GitHub work uses verified App authority and internal resync.

Stale remote branch deletion first proves no active cleanup authority,
refreshes exact branch/target refs, checks ancestry and uses leased deletion.
Ambiguous or concurrently changed refs remain for retry. Local worktree/branch
warnings require proof of cleanliness and ancestry to the intended base;
`git branch -d` checks current HEAD, not an arbitrary intended base.

One external follow-on remains for missing-worktree reference warnings:

```sh
git worktree prune
```

Report all other issues for human review or the normal work-item pipeline.
After `--fix`, re-run the same command/scope and show the updated summary.

## 3. Release before final output

```sh
yoke claims work release --claim-id {claim_id} --reason doctor_complete --json
```

Always attempt release; log a release refusal from its envelope without
suppressing the report. Display the report, and name a saved file only when
`--file` was supplied. Remaining issues go through `/yoke idea` and the normal
pipeline.
