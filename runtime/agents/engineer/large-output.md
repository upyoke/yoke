# Engineer — Large Output Handling

Reference content for the canonical engineer prompt at `runtime/agents/engineer.md`. Read this file when running test suites or any command whose output may be large. Outputs that exceed tool limits waste tool call cycles and lose information; the rules below prevent oversized outputs and recover when they occur.

## Test Suite Execution

- **Capture once, inspect many times:** Never rerun a full suite just to recover failure lines from already-produced output. Capture to a temp file and inspect multiple ways in a single invocation:
  ```bash
  _tmp=$(mktemp /tmp/yoke-test.XXXXXX)
  sh tests/test-foo.sh >"$_tmp" 2>&1; _rc=$?
  tail -50 "$_tmp"                          # summary (includes failure labels for helper-based suites)
  grep -E "FAIL|ERROR|error" "$_tmp" || true # extract failures from full output
  rm -f "$_tmp"
  exit "$_rc"
  ```
- **Helper-based suites replay failure labels:** Suites sourcing `test-helpers.sh` replay failed assertion labels in `test_summary()`. For most helper-based failures, `tail -50` now includes the pass/fail counts plus the replayed labels. If there are too many failure lines to fit, inspect the captured file directly for the full list.
- **For long runs (>60s), prefer the watcher wrapper.** Generic `mktemp /tmp/yoke-test.XXXXXX` capture is a blocking foreground pattern — for any test run that may exceed ~60s, use `python3 -m yoke_core.tools.watch_pytest -- <pytest args>` instead. The wrapper streams progress through its own stdout, mints raw + filtered capture files via `yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair("pytest")` under the machine temp root's watcher-captures directory, and prints the resolved paths so you can `tail -80 <raw-capture>` after exit. Do NOT hand-construct an OS-temp literal for the watcher capture — read the path the wrapper printed. Operator carve-out: pass `--raw-capture <path>` to pin the capture file to a known location (CI / artifact collection); the helper-resolved default is preferred.
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

- **Prefer targeted extraction over full reads:** use `grep`, `tail`, `head` via Bash before reading an entire file.
- **Preemptively limit output:** when a Bash command might produce large output, pipe through `tail -N` or `head -N`. **Exception: test suites** — never pipe test runs through `tail` or `head` directly. Always use the capture-to-temp-file pattern above so failures are preserved and inspectable without re-running.
- **Never read a temp file blind:** always check its line count with `wc -l` first. If over 500 lines, use targeted reads.
