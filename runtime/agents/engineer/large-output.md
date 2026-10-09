# Engineer — Large Output Handling

Read before commands with large output. Capture once; the saved file answers
every later question without rerunning tests for failure lines.

```bash
_tmp=$(mktemp /tmp/yoke-test.XXXXXX)
<project test command> >"$_tmp" 2>&1; _rc=$?
tail -50 "$_tmp"
rg -n 'FAIL|ERROR|error' "$_tmp" || true
exit "$_rc"
```

Use registered project verification, never invented tracked `.sh` runners.
Helper summary replay often includes failure labels in tail; read more of the
same capture when necessary. Debug the failing test alone, not another sweep.

For runs likely >60s use `yoke watch pytest -- <args>` instead. It streams
progress and owns raw/filtered files from
`yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair("pytest")` in
machine temp-root watcher-captures. Read printed paths; never construct them.
After exit inspect `tail -80 <raw-capture>`. Explicit `--raw-capture <path>` may
pin CI/artifact capture; helper default preferred. Continue same yielded handle
to exit; do not duplicate, background a subagent waiter or manually poll.

## Size-aware reads and recovery

Before reading any temp file inspect `wc -l < <file>`. Over500lines: targeted
tail/ranges/search, never blind full read. Read token-limit failure requires
immediate offset/limit recovery: test summaries near end, source ranges found
with scoped search. Never abandon needed information or rerun to recover it.

## Narrow command answers

<!-- BEGIN GENERATED: read-recipe -->
Want part of an answer? Ask the narrow question — every read has a shape that serves it.

```text
yoke <command> <arguments>      # the routine answer, already scoped
yoke items get PREFIX-N status  # the fields you name
tail -80 <raw-capture>          # the capture a watcher prints, once it exits
```
<!-- END GENERATED: read-recipe -->

Help carries this recipe; root --help owns catalog. Registered reads serve the
requested shape whole. rg/sed/tail/head extract files/captures, never truncate a
live long invocation. Watcher capture or capture-first file preserves full
failure context for repeated inspection.
