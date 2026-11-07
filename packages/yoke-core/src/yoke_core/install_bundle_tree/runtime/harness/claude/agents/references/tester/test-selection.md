## Selecting and Running Tests

Run every test a criterion names and the tests for each changed file; add the
callers that import changed code. Widen for core, shared, schema or
cross-cutting changes, but do not default to an exhaustive sweep: the item's
QA case owns the full run. Explain what you selected and excluded. Every
selected test must pass.

In Yoke, use `yoke watch pytest --impacted main`, or targeted files after
`--`. A remote run needs a committed lane; read the paths the wrapper prints
and inspect `tail -80 <raw-capture>` after it exits. For any other command,
capture once and read the capture:

```bash
_tmp=$(mktemp /tmp/yoke-test.XXXXXX)
<project test command> >"$_tmp" 2>&1; _rc=$?
tail -50 "$_tmp"
rg -n 'FAIL|ERROR|error' "$_tmp" || true
exit "$_rc"
```

Run long commands in the foreground, inside one Bash call, to their end. Never
background them or arm a Monitor: a subagent turn cannot receive that later
wake, and the parent dispatch stalls. If your turns cannot cover a run, return
a tighter scope to the parent.

After the tests, compare `git -C {worktree-path} status --porcelain` with the
expected changes. Untracked files the tests left behind fail the verdict.
