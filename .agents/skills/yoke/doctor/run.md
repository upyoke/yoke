# /yoke doctor — run the roster and write the report

## 0. Session Claim

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active doctor). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode doctor
```

Register an exclusive work claim to prevent concurrent doctor sessions and
retain the returned `claim_id` for the release invariant:

```bash
yoke claims work acquire --process DOCTOR --project {project} \
  --reason doctor_run --json
```

If the response carries `error.code="claim_conflict"` (another session
holds the process key), print:

> Another session is already running `/yoke doctor`. Only one doctor session can run at a time. Wait for it to finish or end the other session first.

Then **stop immediately.** Do not run the doctor engine or produce any output.

**Release invariant:** Once the `DOCTOR` claim is acquired, every remaining exit path MUST release it. If you need to stop before the normal completion path, call:

```bash
yoke claims work release --claim-id {claim_id} --reason doctor_stop --json
```

Do not leave the `DOCTOR` claim active after any post-claim stop.

1. **Run the health check engine:**

 One shape on every machine: `yoke watch doctor`. It wraps the
 transport-keyed `yoke doctor run`, so there is no connection to inspect
 and no branch to pick. A relayed control plane chunks the run into
 bounded server requests and composes the source-tree HCs from this
 machine's checkout; a local-Postgres connection runs the whole roster
 in process. Either way the wrapper preserves the raw report and streams
 the same per-check progress lines, which is what AGENTS.md `## Command
 Output — Hard Rule` requires of a run this long.

 Pass bare doctor args after `--`:
 - **`--full`** for operator-invoked `/yoke doctor` — runs every HC including
   GitHub-dependent ones. This is the right scope when the operator wants a
   full system check; expect ~10-20 `gh` subprocess calls per run.
 - **`--quick`** when the caller doesn't need the GitHub reconciliation HCs
   (the polish/verify path uses this; never uses gh quota). Use only when
   you're certain the gh-dependent drift doesn't matter for this run.
 - **`--only <slug[,slug...]>`** to narrow to specific HCs.
 - If a project was specified (first positional arg), pass `--project {project}`
 - If no project was specified, default to `--project yoke`
 - If `--file {path}` was specified, pass `--file {path}`
 - If `--fix` was specified, pass `--fix`
 - Otherwise, the engine uses its default path (`ouroboros/health/health-{YYYYMMDD}.md`)

 For `/yoke doctor` the canonical scope is `--full`:

 ```bash
 yoke watch doctor -- --full --project {project} [--file {path}] [--fix]
 ```

 The run prints the Ouroboros Health Report on either transport, and
 `--file` also writes it to that path. Only claim a report file when
 `--file` was passed.

 Without a scope flag the run exits 2 with a teachable error naming the
 three options. This is intentional: every caller must make an explicit
 GitHub-quota choice — automated verification paths use `--quick`,
 operator-invoked health checks use `--full`. The wrapper preserves the
 underlying exit code so this branching still works.

 Capture both the exit code and the full stdout output (the Ouroboros Health Report).

2. **Display the health report:**

 Show the full report output to the user. The report includes:
 - Summary line (N passed, N warnings, N failures)
 - Failures section (if any)
 - Warnings section (if any)
 - Passed section

3. **Handle `--fix` flag (auto-repair):**

 **If `--fix` was NOT specified:** Skip auto-repair and continue to step 5 so the `DOCTOR` claim is released before final output.

 **If `--fix` was specified:** Most repair happens **inside** the selected
 engine — the Step 1 command already applied fixes. The engine handles:

- **Bidirectional GitHub sync** (orphan reconciliation; title, body, label, state, and frozen drift) via internal delegation to the resync engine in doctor format. Pushes local truth to GitHub and creates/closes/migrates issues as needed.
 - **Stale remote branches** of done or cancelled items, after proving the
   owning item has no active cleanup authority, refreshing the exact branch and
   target refs, proving ancestry, and using a leased delete. Ambiguous or
   concurrently updated refs are preserved for a later retry.
 - **Stale local worktree/branch warnings** are reported with remediation text, but manual cleanup must still prove the worktree is clean and the branch tip is an ancestor of the intended base; `git branch -d` checks the current checkout's `HEAD`, not an arbitrary stage/main base.
 - **Wrong-repo GitHub issues** (migrates issues between repos when the project's `github_repo` capability has moved).
 - **Orphaned temp files / scratch directories** (`rebuild-board.*`, `sync-to-github.*`).

 The agent applies one narrow follow-on fix that the engine does not handle directly:

 **Stale worktree references** (HC-worktree-health warnings about missing worktrees) — `git worktree prune` is a retained external boundary (git porcelain) and stays as a Bash call:

 ```bash
 git worktree prune
 ```

 **All other warnings/failures:** Report only. These require human review, code changes, or the normal issue/work item pipeline. Display a note:
 ```
 The following issues require manual attention:
 {list non-fixable issues from the report}
 ```

4. **If `--fix` was applied, re-run the doctor engine:**

 After applying fixes, re-run the same transport-selected command from Step 1
 with the same scope to verify the fixes took effect. Display the updated
 summary.

5. **Release DOCTOR Claim:**

 Release the exclusive work claim so the session can end naturally or be reused.

 ```bash
 yoke claims work release --claim-id {claim_id} \
   --reason doctor_complete --json
 ```

 **Important:** This MUST run regardless of whether `--fix` was applied or whether there were failures. Read-only doctor runs without `--fix` still come here before final output. A release failure is logged via the response envelope but does not block the report.

6. **Final output:**

 Display the report. When `--file {path}` was passed, name where it
 was written:
 ```
 Ouroboros health report saved to: {path}
 ```

 Without `--file` there is no report file — display the report the run
 printed; do not invent a filesystem path.

 If there were failures that could not be auto-fixed:
 ```
 {N} issues remain. File work items via /yoke idea and fix through the normal pipeline.
 ```

