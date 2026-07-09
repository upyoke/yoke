# Conduct — Cleanup & Report (6z, 6z-cleanup, 7)

The cleanup-and-report phase of the conduct epic flow. Board rebuild, main-repo cleanup, final report, and claim release. Runs on **every exit path** — SUCCESS, HALTED, `--no-chain`, and skip-simulation. **Inherited:** `MAIN_ROOT`, `N`, `_epic_id`, `_title`.

---

## 6z. Board Rebuild

Before the final report, trigger a single board rebuild to consolidate
all intermediate transitions that were suppressed with `--no-rebuild`.
Dispatch the `board.rebuild.run` function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
`target = {kind: "global"}`, `payload = {force: false}`.

This replaces the per-transition rebuilds that previously caused lock
contention during fast conduct loops. Run the board rebuild before
every transition to step 7, including SUCCESS, HALTED, `--no-chain`,
and skip-simulation exits.

After the board rebuild, always proceed to **step 6z-cleanup** (Main-Repo Cleanup) before step 7.

## 6z-cleanup. Main-Repo Cleanup

After the board rebuild and before the final report, clean up shared-state artifacts that conduct leaves on main (gap-ticket filing, board rebuilds, view regeneration). This step runs on every exit path — SUCCESS, HALTED, `--no-chain`, and skip-simulation.

### a. Remove orphaned temp files

Resolve cleanup against the owning main repo root, not the active linked worktree root.
When conduct runs from a linked worktree, shared temp files and generated views live on
the main repo. Use `MAIN_ROOT` (inherited from conduct context) which already points at
the correct main repo root via the conduct router's internal main-worktree resolver.
Do NOT use `git rev-parse --show-toplevel` here — it resolves to the worktree, not main.

The cleanup must be null-safe under both zsh and bash. Do not rely on unmatched shell
globs falling through to the loop body — zsh raises `nomatch` before the guard runs.
Use `find` so the cleanup behaves the same on both shells. Missing temp files are a
normal no-op, not a conduct failure.

```bash
# MAIN_ROOT (inherited context variable) points at the owning main repo root.
# Set by the conduct router's internal main-worktree resolver.
_yoke_dir="${MAIN_ROOT}/data"
_cleaned_temps=$(
 find "$_yoke_dir" -maxdepth 1 -type f \
 \( -name 'BOARD.md.lock' -o -name 'BOARD.md.board.*' -o -name 'BOARD.md.reg_*' -o -name 'BOARD.md.ts' \) \
 -print 2>/dev/null | sed 's|.*/||'
)
if [ -n "$_cleaned_temps" ]; then
 find "$_yoke_dir" -maxdepth 1 -type f \
 \( -name 'BOARD.md.lock' -o -name 'BOARD.md.board.*' -o -name 'BOARD.md.reg_*' -o -name 'BOARD.md.ts' \) \
 -exec rm -f {} +
fi
```

If any were removed, note them:
> Cleaned orphaned temp files:{_cleaned_temps}

### b. Normalize generated-view index state

The generated board view (`.yoke/BOARD.md`) is gitignored. After worktree/main divergence it can end up in unmerged (`DU`/`AU`) index state. Reset it silently — it is regenerated on demand and must never be committed:

```bash
_stale_views=$(git -C "$MAIN_ROOT" status --porcelain -- .yoke/BOARD.md 2>/dev/null | grep -E '^(DU|AU|UU) ' || true)
if [ -n "$_stale_views" ]; then
 git -C "$MAIN_ROOT" reset --quiet HEAD -- .yoke/BOARD.md 2>/dev/null || true
 git -C "$MAIN_ROOT" checkout HEAD -- .yoke/BOARD.md 2>/dev/null || true
 git -C "$MAIN_ROOT" clean -fdX -- .yoke/BOARD.md 2>/dev/null || true
fi
```

If any were normalized:
> Normalized generated-view index state (gitignored views were in unmerged state).

### c. Report remaining artifacts

Check for any remaining non-clean state on main:

```bash
_remaining=$(git -C "$MAIN_ROOT" status --porcelain -- data/ 2>/dev/null | head -5)
```

If non-empty, include in final report:
> **Advisory:** Main has remaining artifacts after cleanup:
> ```
> {_remaining}
> ```

### d. Report unpushed commits on main

```bash
_unpushed=$(git -C "$MAIN_ROOT" log origin/main..main --oneline 2>/dev/null || true)
```

If non-empty, include in final report:
> **Note:** Main is ahead of origin with unpushed commits:
> ```
> {_unpushed}
> ```
> Consider pushing bookkeeping commits or including them in the next PR.

---

## 7. Final Report

Print `CONDUCT_RESULT: {SUCCESS|HALTED}` with a per-item summary. Next step guidance: issue success -> `/yoke usher YOK-{N}`; epic success -> `/yoke usher YOK-{N}`; halted (testing) -> review Tester reports, re-run `/yoke conduct YOK-{N}`; halted (simulation gaps) -> review simulation gaps, fix integration issues in worktree, then re-run `/yoke conduct YOK-{N}` (worktree preserved). See `error-handling.md` for notes.

**Halted (simulator epic-identity attestation):** when conduct halts because `persist_simulation` exited 16 (wrong-epic body) or 17 (missing-epic body), the operator-facing line MUST preserve the exact `persist_simulation` error text. Exit 16's error names both the CLI-passed epic and the body-attested epic; relay that text in the final report rather than collapsing it to a generic "simulation halted" line. The operator needs to see *which* epic was attested vs *which* epic was passed so they can decide whether to re-dispatch with corrected context, file a follow-up against the prompt assembly path, or investigate parent-session compaction. The same rule applies when the Layer 4 defensive bail halts conduct because `_epic_id` was empty before dispatch — surface that exact `_epic_id lost between dispatches` line, not a paraphrase.

### Release Manual Work Claims

On SUCCESS exits, the claim was already released by `conduct_reviewed_handoff` with reason `handoff-to-polish`. On HALTED exits, release the parent item claim as a fallback:

```bash
# Fallback release for halted/bypassed paths only (success path is Python-owned T-4)
yoke claims work release \
 --item "YOK-${N}" --reason "completed" >/dev/null 2>&1 || true
```
