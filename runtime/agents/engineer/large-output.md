# Engineer — Large Output Handling

Capture a large output once and answer every later question from the capture;
never rerun a command to see more of its output.

```bash
_tmp=$(mktemp /tmp/yoke-test.XXXXXX)
<command> >"$_tmp" 2>&1; _rc=$?
tail -50 "$_tmp"
rg -n 'FAIL|ERROR|error' "$_tmp" || true
exit "$_rc"
```

`yoke watch pytest` captures for you: read the paths it prints, never build
them, and after it exits inspect `tail -80 <raw-capture>`.

Check `wc -l < <file>` before reading a capture. Over 500 lines, read targeted
ranges or search; when a read hits the token limit, retry with an offset and
limit at once.

## Narrow command answers

<!-- BEGIN GENERATED: read-recipe -->
Want part of an answer? Ask the narrow question — every read has a shape that serves it.

```text
yoke <command> <arguments>      # the routine answer, already scoped
yoke items get PREFIX-N status  # the fields you name
tail -80 <raw-capture>          # the capture a watcher prints, once it exits
```
<!-- END GENERATED: read-recipe -->

Cut files and captures with `rg`, `sed` or `tail`; never pipe a live `yoke`
command into `head` or `tail`.
