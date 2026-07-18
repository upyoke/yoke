# Polish — Gather Context

Covers polish steps 4 and 5: gather item artifacts and survey the surrounding landscape for drift, overlap, and staleness.

**Context variables** (set by parse-and-claim): `ITEM_NUM`, `WORKTREE_PATH`, `WORKTREE_PATHS`.

---

## 4. Gather Context

Read the item's artifacts to understand the intended implementation:

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
ITEM_NUM=$(printf '%s' "{arg}" | sed 's/^[Ss][Uu][Nn]-//; s/^0*//')
SPEC=$(yoke items get "$ITEM_NUM" spec 2>/dev/null) || true
BODY=$(yoke items get "$ITEM_NUM" body 2>/dev/null) || true
TECHNICAL_PLAN=$(yoke items get "$ITEM_NUM" technical_plan 2>/dev/null) || true
TEST_RESULTS=$(yoke items get "$ITEM_NUM" test_results 2>/dev/null) || true
```

Use spec (or body fallback) to identify:
- Acceptance criteria
- Scope boundaries
- Likely files and tests that matter

## 5. Contextual Survey

**This step is critical.** Polishing in isolation misses codebase drift and cross-ticket conflicts. Before reviewing the implementation, survey the surrounding landscape.

**Recent commits on main** — What has landed since this branch diverged? The implementation may conflict with or duplicate recent work.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
git -C "$MAIN_ROOT" log --oneline -20
if [ -n "{WORKTREE_PATH}" ]; then
 git -C "{WORKTREE_PATH}" log --oneline main..HEAD
else
 while IFS= read -r _wt; do
  [ -n "$_wt" ] || continue
  printf '\n# %s\n' "$_wt"
  git -C "$_wt" log --oneline main..HEAD
 done <<'EOF'
{WORKTREE_PATHS}
EOF
fi
```

Scan for main-branch commits that touch the same files or subsystems as this branch. If recent work on main has:
- Changed APIs or signatures this branch calls → the branch may need rebasing or adaptation.
- Already implemented part of this ticket's scope → flag for descoping.
- Renamed or removed things this branch references → the branch has stale references.

**Active and pipeline tickets** — What else is in flight that might overlap or conflict?

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
yoke db read --format lines "SELECT id, status, title FROM items WHERE status IN ('implementing','reviewing-implementation','reviewed-implementation','polishing-implementation','refining-idea','refined-idea','planning','refining-plan','planned') ORDER BY id DESC"
```

Look for:
- **Overlap** — another ticket modifying the same files. If two branches touch the same code, note the merge-order risk.
- **Supersession** — a broader ticket that subsumes this one's remaining work.
- **Dependencies** — a ticket that must land first, or that depends on this one landing first.

**Recently done tickets** — What just shipped that might affect this branch?

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
yoke db read --format lines "SELECT id, title FROM items WHERE status='done' ORDER BY id DESC LIMIT 15"
```

Check whether recently completed work has changed the codebase in ways that make parts of this implementation stale, redundant, or conflicting.

**Staleness synthesis** — Carry ALL findings into the review phase (`.agents/skills/yoke/polish/review.md`). Staleness and cross-ticket conflicts are first-class polish issues. If the branch needs rebasing, flag it before making fixes. If scope should be reduced because another ticket already covered part of the work, note it in the review.
