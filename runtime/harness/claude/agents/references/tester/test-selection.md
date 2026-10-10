## Selecting and Running Tests

Read before selecting. Run every AC-listed test and matching changed file/
command tests; consider dependent/importing callers. Broaden for core/shared/
schema/cross-cutting risk; do not default to exhaustive sweep. Explain selected,
considered/excluded coverage and rationale in report. All selected tests pass.

Yoke: `yoke watch pytest --impacted main --bounded`. Contract floor retained,
unbounded selection reported rather than silently widened. Project CI capability
routes exact committed lane to CI; commit required, dirty tree refuses. Small
targeted --local expected<=minute, not slow dirty-tree justification. Protected
CI owns full sweep; local full only sanctioned CI outage fallback. QA case is
one full execution per tree; no duplicated sweep. Use project declared anchors,
never copied another project's layout.

Capture once before inspection, never live-pipe to tail/head:

```bash
_tmp=$(mktemp /tmp/yoke-test.XXXXXX)
<project test command> >"$_tmp" 2>&1; _rc=$?
tail -50 "$_tmp"
rg -n 'FAIL|ERROR|error' "$_tmp" || true
exit "$_rc"
```

Long runs use `yoke watch pytest -- <args>` (merge watcher only when explicitly
assigned orchestration), preserving raw capture and selected harness wait.
Read printed capture after exit, not constructed temp paths; explicit --raw-capture
may pin artifact output. Continue yielded handle to exit, no duplicate invocation.
Dispatched turns are atomic: long commands run foreground in one Bash call,
never background with Monitor and return. Later wake has no receiver and stalls
parent. Capture helper `project_scratch_dir.watcher_capture_path(...)` owns
printed path; inspect `tail -80` after completion. If budget cannot cover run,
return tighter scope to parent, no detached waiter. Read session.md Tool Constraints.

No-regression ACs require regression-detection.md trust/signature procedure;
equal totals are not proof. After tests check `git -C {worktree-path} status
--porcelain` against expected touched paths. Unexpected untracked files/directories
are test artifact leak and FAIL, never ignored merely because tests passed.
