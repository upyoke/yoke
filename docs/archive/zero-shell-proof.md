# Zero-Shell Proof

This document records the proof that Yoke reached literal zero shell on `main`.

## Establishing Commits

- `db4762d28` — first `main` commit where `git ls-files '*.sh'` returned `0`
- This proof artifact commit records the post-merge verification and doc refresh on top of that zero-shell trunk state

## Proof Commands

Run from `/Users/dev/yoke`:

```bash
git rev-parse --short HEAD
git ls-files '*.sh' | wc -l
python3 -m runtime.api.tools.shell_inventory --repo-root /Users/dev/yoke --output docs/shell-inventory.md
python3 -m pytest runtime/api/
python3 -m runtime.api.engines.doctor --quick
```

## Recorded Results

- `git ls-files '*.sh' | wc -l` -> `0`
- `python3 -m pytest runtime/api/` -> full Yoke API suite passed on the zero-shell branch
- `python3 -m runtime.api.engines.doctor --quick` -> `0 failures`
- [shell-inventory.md](shell-inventory.md) reports:
  - `Total .sh files: 0`
  - `Remaining literal-zero-shell gap: 0`
  - `Real Python migration queue: 0 files / 0 shell lines`

## Operator-Facing Contract

Literal zero shell means operators no longer invoke repo-tracked shell entrypoints directly. The canonical entrypoints are now Python-owned:

- Backlog and DB access: `python3 -m runtime.api.cli.db_router ...`
- Public backlog mutation surface: `python3 -m runtime.api.service_client backlog-cli ...`
- Harness bootstrap: `python3 -m runtime.harness.codex.codex_entry bootstrap`
- Hook execution: git-root-stable `env PYTHONPATH="$(git rev-parse --show-toplevel)${PYTHONPATH:+:$PYTHONPATH}" python3 -m runtime.harness.codex.codex_hooks ...` and `python3 -m runtime.harness.session_hooks ...`
- Test runner: `python3 -m runtime.api.tools.run_tests`
- API lifecycle: `python3 -m runtime.api.tools.api_server {start,restart,stop}`

## Skill-Internal Contract (YOK-1438)

The original zero-shell proof (above) established that no tracked `.sh` entrypoints remain. YOK-1438 broadened the contract to cover shell glue *inside* skill prompts — Bash blocks in `.agents/skills/yoke/**/*.md` that existed only to choreograph arguments, session state, or content into Python-owned surfaces.

### Prohibited patterns

These patterns are banned in skill files and enforced by regression tests in `test_zero_shell_proof.py`:

- **Session-ID fallback chains.** Shell code like `_sid="${YOKE_SESSION_ID:-${CLAUDE_SESSION_ID:-${CODEX_THREAD_ID:-}}}"` is eliminated. Python CLIs resolve the session ID internally via `_resolve_session_id()` in `service_client.py`.
- **Path-based `service_client.py` invocations.** Skills must not call `python3 "$YOKE_ROOT/runtime/api/service_client.py"` or similar path-based wrappers. Use `python3 -m runtime.api.service_client` instead.
- **`mktemp`/`rm -f` choreography for content writes.** Skills must not create temp files solely to pass content to `--body-file`. Use `--stdin` with a heredoc or pipe, or use the Write tool followed by `--body-file` when a real file artifact is needed.

### Intentionally retained shell boundaries

The following shell usage in skills is legitimate and explicitly outside the prohibition:

- **Project test commands** — `sh -c` invocations of user-provided test commands.
- **grep/discovery** — repo-level file search and content inspection.
- **git inspection** — `git diff`, `git log`, `git status`, branch operations.
- **Diff and screenshot temp files** — intermediate artifacts for diffs, screenshots, QA batches, and evidence assembly where the content is built across multiple steps.
- **`check_hard_blocks` output capture** — shell capture of Python command output for conditional logic.
- **Single-command `db_router` calls** — one-line `python3 -m runtime.api.cli.db_router ...` invocations are not shell glue.

### Regression coverage

`runtime/api/test_zero_shell_proof.py` enforces the skill-internal contract with these tests:

- `test_no_session_id_fallback_chains_in_skills` — asserts zero `_sid` fallback chains across all skill files.
- `test_no_content_write_mktemp_in_skills` — asserts zero `mktemp` usage for structured content write paths.
- `test_no_service_client_script_path_in_skills` — asserts zero path-based `service_client.py` calls.

## Acceptance Summary

- AC-1: On `main`, tracked shell count is zero.
- AC-2: Proof coverage exists in [test_zero_shell_proof.py](/Users/dev/yoke/runtime/api/test_zero_shell_proof.py).
- AC-3: This document records the exact commands, results, and commit lineage.
- AC-4: Top-level operator docs now point to Python entrypoints instead of repo-tracked shell commands.
