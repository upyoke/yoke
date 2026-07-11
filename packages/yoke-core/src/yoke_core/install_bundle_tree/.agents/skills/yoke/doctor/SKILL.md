---
name: doctor
description: Run the Ouroboros health scan for Yoke or a specific project. Checks backlog consistency, GitHub sync, worktrees, docs drift, dispatch chains, agents, hooks, and project-specific diagnostics.
argument-hint: "[project] [--fix] [--file path]"
---

# /yoke doctor

Run the Ouroboros system health scan. Checks the Yoke installation for consistency, drift, and breakage. When a project is specified, runs additional project-specific diagnostics. Branded as the **Ouroboros Health Report**.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `[project]` — Target project for project-specific checks (default: `yoke`). Examples: `buzz`, `yoke`. The first positional argument that is not a flag is treated as the project name.
- `--fix` — Auto-repair trivial issues (label mismatches, stale dashboards, stale worktree refs). Non-trivial issues are reported only.
- `--file {path}` — Save the report to a custom path (default: `ouroboros/health/health-{YYYYMMDD}.md`)

## Philosophy

**Events table as health signal.** The events table captures anomaly patterns across all agent sessions. Include `yoke events anomalies --since "24 hours ago"` in the diagnostic context. Elevated anomaly counts or recurring `nonzero_exit` patterns on specific scripts are health signals.

## Steps

### 0. Session Claim

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active doctor). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode doctor
```

Register an exclusive work claim to prevent concurrent doctor sessions.
Call `claims.work.acquire` with a process-keyed target.

```json
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "process", "process_key": "DOCTOR", "conflict_group": "yoke"},
  "intent": "doctor_run",
  "payload": {"target": {"kind": "process", "process_key": "DOCTOR", "conflict_group": "yoke"}, "reason": "doctor_run"}
}
```

If the response carries `error.code="claim_conflict"` (another session
holds the process key), print:

> Another session is already running `/yoke doctor`. Only one doctor session can run at a time. Wait for it to finish or end the other session first.

Then **stop immediately.** Do not run the doctor engine or produce any output.

**Release invariant:** Once the `DOCTOR` claim is acquired, every remaining exit path MUST release it. If you need to stop before the normal completion path, call:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "doctor_stop",
  "payload": {"claim_id": <claim_id>, "reason": "released"}
}
```

Do not leave the `DOCTOR` claim active after any post-claim stop.

1. **Run the health check engine:**

 Invoke doctor through the watcher wrapper `python3 -m yoke_core.tools.watch_doctor`
 — per AGENTS.md `## Command Output — Hard Rule`, every doctor run goes through
 the watcher to avoid the `2>&1 > file` redirection trap that silently strips
 stderr to the void (observed live cascading into multi-tool recovery loops).
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

 For `/yoke doctor` the canonical invocation is `--full`:

 ```
 python3 -m yoke_core.tools.watch_doctor -- --full --project {project} [--file {path}] [--fix]
 ```

 Without a scope flag the engine exits 2 with a teachable error naming the
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

 **If `--fix` was specified:** Most repair happens **inside** the engine — `python3 -m yoke_core.tools.watch_doctor -- --fix` already applied fixes during step 1. The engine handles:

- **Bidirectional GitHub sync** (orphan reconciliation; title, body, label, state, and frozen drift) via internal delegation to the resync engine in doctor format. Pushes local truth to GitHub and creates/closes/migrates issues as needed.
 - **Stale remote branches** of done or cancelled items, after proving the
   owning item has no active cleanup authority, refreshing the exact branch and
   target refs, proving ancestry, and using a leased delete. Ambiguous or
   concurrently updated refs are preserved for a later retry.
 - **Stale local worktree/branch warnings** are reported with remediation text, but manual cleanup must still prove the worktree is clean and the branch tip is an ancestor of the intended base. Use `docs/source-dev-worktree-cleanup.md`; `git branch -d` checks the current checkout's `HEAD`, not an arbitrary stage/main base.
 - **Wrong-repo GitHub issues** (migrates issues between repos when the project's `github_repo` capability has moved).
 - **Orphaned temp files / scratch directories** (`rebuild-board.*`, `sync-to-github.*`).

 The agent applies two narrow follow-on fixes that the engine does not handle directly:

 **a) Stale dashboard counts** (HC-doc-drift warnings that mention dashboard or board widgets) — trigger a board rebuild via the function call:

 ```json
 {
   "function": "board.rebuild",
   "actor": {"session_id": "<this-session>"},
   "target": {"kind": "global"},
   "intent": "doctor_dashboard_repair"
 }
 ```

 **b) Stale worktree references** (HC-worktree-health warnings about missing worktrees) — `git worktree prune` is a retained external boundary (git porcelain) and stays as a Bash call:

 ```bash
 git worktree prune
 ```

 **All other warnings/failures:** Report only. These require human review, code changes, or the normal issue/ticket pipeline. Display a note:
 ```
 The following issues require manual attention:
 {list non-fixable issues from the report}
 ```

4. **If `--fix` was applied, re-run the doctor engine:**

 After applying fixes, re-run `python3 -m yoke_core.tools.watch_doctor -- <same scope flags as step 1>` to verify the fixes took effect. Display the updated summary.

5. **Release DOCTOR Claim:**

 Release the exclusive work claim so the session can end naturally or be reused.

 ```json
 {
   "function": "claims.work.release",
   "actor": {"session_id": "<this-session>"},
   "target": {"kind": "claim", "claim_id": <claim_id>},
   "intent": "doctor_complete",
   "payload": {"claim_id": <claim_id>, "reason": "completed"}
 }
 ```

 **Important:** This MUST run regardless of whether `--fix` was applied or whether there were failures. Read-only doctor runs without `--fix` still come here before final output. A release failure is logged via the response envelope but does not block the report.

6. **Final output:**

 Display the report file path:
 ```
 Ouroboros health report saved to: {path}
 ```

 If there were failures that could not be auto-fixed:
 ```
 {N} issues remain. File tickets via /yoke idea and fix through the normal pipeline.
 ```

## Notes

- The doctor engine exits 0 if no FAILs, exits 1 if any FAILs (the watcher wrapper at `python3 -m yoke_core.tools.watch_doctor` preserves this exit code). Use the exit code to determine overall health.
- GitHub-dependent health checks (sync-completeness-legacy, orphan/missing/comment-sync HCs) resolve the project's verified App binding through `yoke_core.domain.project_github_auth.resolve_project_github_auth` and call GitHub REST/GraphQL with a short-lived installation token — they do NOT require the host `gh` CLI. Bidirectional sync HCs delegate detection and repair to the internal resync engine in doctor format, which uses the same resolver. The doctor engine forwards `--fix` automatically; the agent never runs a host shell-out itself.
- The `--fix` flag only repairs trivial, deterministic issues. It never modifies code, agent prompts, or SKILL.md files.
- Bulk-mutation awareness: a single `/yoke doctor --fix` invocation can push large numbers of GitHub edits (every body, title, label, and state drift on every paired item). Before running `--fix` on a long-stale install, do a read-only pass first and confirm the mutation volume is acceptable.
- Run `/yoke doctor` periodically or after significant changes to catch drift early. This is part of Ouroboros — Yoke's self-improvement system.
- HC-doc-health (Documentation health audit) findings are not auto-fixable. Missing READMEs, broken links, stale docs, and undocumented features require manual attention.
- HC-deferred-items (Deferred items enforcement) scans done epics for UNFILED deferred items and untracked deferral language. Not auto-fixable — requires filing follow-up items via `/yoke idea` and updating the epic's `## Deferred Items` section.
- **Project-specific checks:** When a project other than `yoke` is specified, doctor runs generic project checks (repository and App binding readiness, stale worktrees) plus project-specific checks. For `buzz`: VPS reachability, GitHub Actions secrets, deployment flow state, health endpoint, orphaned worktrees. If the project is not found in the DB, a warning is emitted and project-specific checks are skipped.
