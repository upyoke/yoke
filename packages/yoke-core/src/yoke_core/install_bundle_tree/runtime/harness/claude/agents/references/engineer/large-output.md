# Engineer — Large Output Handling

Reference content for the Engineer prompt. Read this file when running test suites or any command whose output may be large. Outputs that exceed tool limits waste tool call cycles and lose information; the rules below prevent oversized outputs and recover when they occur.

## Test Suite Execution

- **Capture once, inspect many times:** Never rerun a full suite just to recover failure lines from already-produced output. Capture to a temp file and inspect multiple ways in a single invocation:
  ```bash
  _tmp=$(mktemp /tmp/yoke-test.XXXXXX)
  <your project's test command> >"$_tmp" 2>&1; _rc=$?
  tail -50 "$_tmp"                          # summary (includes failure labels for helper-based suites)
  grep -E "FAIL|ERROR|error" "$_tmp" || true # extract failures from full output
  rm -f "$_tmp"
  exit "$_rc"
  ```
  Substitute the project's own registered verification command; this repo's conventions forbid tracked `.sh` test files, so never invent one.
- **Helper-based suites replay failure labels:** Suites whose harness replays failed assertion labels in a summary function make `tail -50` carry the pass/fail counts plus the replayed labels. If there are too many failure lines to fit, inspect the captured file directly for the full list.
- **For long runs (>60s), prefer the watcher wrapper.** Generic `mktemp /tmp/yoke-test.XXXXXX` capture is a blocking foreground pattern — for any test run that may exceed ~60s, use `yoke watch pytest -- <pytest args>` instead. The wrapper streams progress through its own stdout, mints raw + filtered capture files via `yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair("pytest")` under the machine temp root's watcher-captures directory, and prints the resolved paths so you can `tail -80 <raw-capture>` after exit. Do NOT hand-construct an OS-temp literal for the watcher capture — read the path the wrapper printed. Operator carve-out: pass `--raw-capture <path>` to pin the capture file to a known location (CI / artifact collection); the helper-resolved default is preferred.
- **Isolate failures:** When investigating a specific failure, run the failing test in isolation rather than re-running the full suite.
- **Size-aware temp files:** When writing test output to a temp file for later reading, check its size before reading:
  ```bash
  wc -l < "$TMPFILE"
  ```
  If the file exceeds 500 lines, read only the tail (`offset` near the end) or use Grep to find the relevant section.

## Read Tool Recovery

- When a Read tool call fails with "exceeds maximum allowed tokens", **immediately retry** with `offset` and `limit` parameters.
- For test output files: read from the end (set `offset` near the last ~500 lines) to get the summary.
- For source files: use Grep to find the relevant section first, then Read with a targeted line range.
- Never abandon a Read after a token-limit failure — the information was needed, so recover it.

## General Large-Output Discipline

- **Ask the narrow question.** A registered `yoke` command serves its answer whole, and every read has a shape that returns the part you want.

<!-- BEGIN GENERATED: read-recipe -->
Want part of an answer? Ask the narrow question — every registered read has a shape that serves just that part.

```text
yoke <command> <arguments>      # the routine answer; every read is already scoped
yoke items get PREFIX-N status  # name fields and a read serves those fields
tail -80 <raw-capture>          # the path a watcher prints; read it once the run exits
```
<!-- END GENERATED: read-recipe -->

  The recipe rides the bottom of every `yoke <command> --help`; `yoke --help` carries the worked catalog.
- **Targeted extraction reads a file on disk:** `grep`, `sed -n`, `tail`, and `head` belong on a source file or on a capture. A watcher wrapper prints its raw capture path, and anything else is captured first with the pattern above — the file then answers as many questions as you have without re-running anything.
- **Never read a temp file blind:** always check its line count with `wc -l` first. If over 500 lines, use targeted reads.
