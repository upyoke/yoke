# Shell Migration Inventory

Generated: 2026-04-11T10:07:39Z
Repo root: `/Users/dev/yoke`

This inventory is the canonical shell-file ledger for the YOK-1246 closeout and the post-merge zero-shell wave that follows it.

## Summary

- Total `.sh` files: **0**
- Disposition counts:
- Category counts:
- Honest read: `0` shell tests / `0` lines are contingent coverage, not the permanent shell floor.
- Remaining literal-zero-shell gap: `0` runtime boundary scripts still need Python entrypoints, plus the tracked shell-test and external-artifact residue above.
- Real Python migration queue: `0` files / `0` shell lines.

## Current Execution Plan

### Where We Are Now (2026-04-11)

- `YOK-1246`, `YOK-1322`, and both grouped residual waves are merged.
  Wave 2 (`YOK-1351` through `YOK-1361`) plus `YOK-1362` and
  `YOK-1363` now live on `main`.
- The repo has reached **semantic** zero-shell: no tracked `.sh` file is
  still classified as needing a fresh Python owner.
- The remaining work is **literal shell extinction**. Every tracked
  `.sh` that survives today is either a compatibility contract, a
  runtime launcher, a shell test harness file, or a tracked external
  artifact template.
- The per-file `Ticket` column below is now the authoritative ownership
  map for the final closeout wave.

### How To Read The Remaining Buckets

- `contingent shell coverage` means tests or harness helpers that only
  exist because shell entrypoints still exist.
- `shell compatibility shim` means semantics already live in
  `runtime.api.*`, but a shell contract still survives for callers.
- `runtime shell boundary` means the file is still acting as a launcher,
  hook, installer, or process wrapper. Wave 3 removes those boundaries
  too by replacing them with Python entrypoints or generated artifacts.
- `migrate to Python` is no longer the gating metric. The real closeout
  metric is **zero tracked `.sh` files**.

### Literal Zero-Shell Objective

- Success for this wave is `git ls-files '*.sh'` returning `0`.
- A shell file whose semantics are already behind `yoke.api` is still
  residue until the shell contract itself disappears.
- External project ops scripts may still be emitted at render/deploy
  time, but they should no longer be tracked as source files in this
  repo. Python or structured-data templates should own their truth.

### Zero-Shell Wave 3

Wave 3 reuses the shared-branch pattern from the prior grouped waves,
but the target is stricter: remove every tracked `.sh`, not just the
semantic shell residue.

```
main
 |-- YOK-1364 worktree ----|
 |-- YOK-1365 worktree ----|
 |-- YOK-1366 worktree ----|
 |-- YOK-1367 worktree ----|
 |-- YOK-1368 worktree ----+--> zero-shell-wave-3 --> YOK-1371 --> main --> YOK-1189
 |-- YOK-1369 worktree ----|         (shared branch)   integration    proof
 |-- YOK-1370 worktree ----|
 `-- YOK-1300 worktree ----'
```

Shared merge branch/worktree:

- Branch: `zero-shell-wave-3`
- Worktree: `/Users/dev/yoke/.worktrees/zero-shell-wave-3`
- Every worker lane branches from that shared head, not from `main`.

#### Worker Lanes

- `YOK-1364` — remove the public DB shell CLI and DB-wrapper family.
  Owns every file whose `Ticket` is `YOK-1364`: the `yoke-db.sh`
  router plus the remaining `*-db.sh` / `query-items.sh` wrapper set
  and their directly-mapped shell tests.
- `YOK-1365` — remove the backlog/lifecycle shell contract. Owns
  `item-db.sh`, backlog registry / sync / done-transition style shells,
  lifecycle gate shims, and their directly-mapped shell tests.
- `YOK-1366` — remove hook, harness, and event shell entrypoints. Owns
  hook/session/event shell surfaces plus `runtime/harness/**` and their
  directly-mapped shell tests.
- `YOK-1367` — remove browser, deployment, and QA shell entrypoints.
  Owns Browser QA shells, deploy pipeline shells, and their
  directly-mapped shell tests.
- `YOK-1368` — remove worktree, merge, and board shell entrypoints.
  Owns worktree/merge utilities, board/render helpers, and their
  directly-mapped shell tests.
- `YOK-1369` — remove utility, installer, and executor shell
  entrypoints. Owns generic helper shims, runtime executors, install /
  start / restart launchers, and their directly-mapped shell tests.
- `YOK-1370` — deshell tracked external artifacts. Owns the project /
  template ops shell files and scaffold entrypoints currently tracked
  under `yoke/projects/**` and `yoke/templates/**`.
- `YOK-1300` — replace the shell test harness with an API-owned runner.
  Owns the generic shell test residue not mapped to another lane,
  plus the shell-test execution surfaces and project test-command
  registry path.
- `YOK-1371` — integration only. Owns shared caller/doc/config cutover,
  final launcher deletion, inventory refresh, and the grouped merge.
- `YOK-1189` — final proof only. Owns the post-merge zero-shell proof
  ledger and the acceptance gate that the tracked shell count is
  literally zero.

#### Shared Integration Surfaces

Worker lanes must not edit these shared surfaces. They are integration-
owned because they cut across multiple lanes:

- `.agents/skills/yoke/**/SKILL.md`
- `.claude/settings.json`, `.codex/hooks.json`, `.claude/rules/**`
- `AGENTS.md` (and its `CLAUDE.md` compat symlink)
- shared docs under `docs/**` that mention more than one lane:
  `shell-inventory.md`, `scripts.md`, `db-reference.md`, `hook-parity-map.md`,
  `test-inventory.md` (archived: `docs/archive/1246-proof.md`, `docs/archive/service-migration.md`)
- global residue greps / final `git ls-files '*.sh'` enforcement

#### File Ownership Contract

- The per-file `Ticket` column below is the exact ownership contract.
- A worker lane owns the shell file, its Python replacement surfaces,
  and the shell tests mapped to that same ticket below.
- If a caller/doc/config surface references more than one worker lane,
  it is `YOK-1371` integration-owned.
- `YOK-1300` owns every shell-test row whose ticket is `YOK-1300`; do
  not poach those generic workflow suites into the feature lanes.
- No worker lane edits another lane's shell file even if the semantics
  are nearby.

#### Safe Parallelism Rules

- One issue = one worktree.
- Branch every worker lane from `zero-shell-wave-3`, not `main`.
- Merge every worker lane back into `zero-shell-wave-3` before running
  `YOK-1371`.
- Keep the shared branch green for the shell files and tests your lane
  deletes. Do not defer branch-green cleanup wholesale to integration.
- Worker lanes do not touch the shared integration surfaces above.

#### Existing Tickets To Reuse

- `YOK-1300` is no longer a side quest. It is Wave 3's shell-test
  harness / API-runner lane.
- `YOK-1189` is no longer a generic proof reminder. It is the final
  zero-shell closeout gate after Wave 3 merges.

#### How To Execute Wave 3

1. Refresh or recreate `/Users/dev/yoke/.worktrees/zero-shell-wave-3`
   on branch `zero-shell-wave-3` from `main`.
2. File / refine `YOK-1364` through `YOK-1370`, plus the updated
   `YOK-1300`, against that shared branch/worktree.
3. Dispatch `YOK-1364` through `YOK-1370` and `YOK-1300` in parallel.
4. Merge worker lanes back into `zero-shell-wave-3` as they clear
   verification.
5. Run `YOK-1371` once every worker lane has landed on the shared
   branch.
6. Merge `zero-shell-wave-3` to `main`.
7. Run `YOK-1189` and fail closeout unless the tracked shell count is
   literally zero.
## File Inventory

| Path | Lines | Callers | Category | Owner | Disposition | Ticket | Why not Python yet? |
|------|------:|--------:|----------|-------|-------------|--------|---------------------|
