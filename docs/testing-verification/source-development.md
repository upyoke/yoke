# Source-development commands

The installed `yoke` launcher and a bare `python3 -m ...` invocation can load
the main checkout while a session's edits live in a claimed worktree. Use one
recipe for any direct source command:

```bash
yoke dev run -- <command>
```

The command resolves the current session's claimed lane, derives every package
source directory and the repo root through `yoke_core.tools._source_pythonpath`,
and makes the lane the child process's working directory. Before execution it
prints the resolved origins for `yoke_contracts`, `yoke_cli`, `yoke_core`,
`yoke_harness`, and `runtime`; a missing or outside-lane origin refuses the run.
This makes the recipe independent of the shell's current directory and exposes
partial source binding immediately.

For example, validate the agent renderer from the lane with:

```bash
yoke dev run -- yoke agents render --target-root .
```

Focused pytest normally goes through `yoke watch pytest`, which already binds
the same resolver and enforces the session's verification-tree claim. Use the
general recipe only for a direct invocation that is not covered by a wrapper:

```bash
yoke dev run -- python3 -m pytest path/to/test_file.py
```

Ruff is a locked development dependency. Lint every changed Python path with:

```bash
uv run --frozen ruff check <changed Python paths>
```

Do not call a checkout-local `.venv/bin/ruff` path or rely on an ambient
Homebrew install.

For a changed-test fallback, first list candidates with:

```bash
git diff --name-only --diff-filter=ACMR <base>...HEAD \
  -- ':(glob)**/test_*.py' ':(glob)**/*_test.py'
```

Review the newline-delimited output, then pass the exact existing paths to
`watch_pytest`. Do not pipe NUL-delimited Git output through `rg -z`, and never
feed a filter diagnostic to pytest as a filename.
