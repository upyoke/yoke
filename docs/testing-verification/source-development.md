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

The child receives the caller's connected-environment selection and machine
config unchanged. `dev run` changes where source resolves; it does not change
which control plane or database the command uses. Put an explicit selection on
the outer command so the lane-sourced child inherits it:

```bash
yoke --env <name> dev run -- <command>
```

Prod-flagged schema and administered-cluster guards still judge that selected
connection inside the child. Pytest is different: `yoke watch pytest` and the
generic test runner isolate fixture-owned databases from any administering
selection, so use those runners for tests instead of relying on `dev run` to
sanitize their environment.

For example, validate the agent renderer from the lane with:

```bash
yoke dev run -- yoke agents render --target-root .
```

A nested `yoke` command binds like the python shape does. Left alone, an
installed launcher resolves a checkout of its own — the canonical launcher
prepends its `YOKE_HOME` package roots ahead of an inherited `PYTHONPATH`, and
a pinned relay launcher runs isolated and never reads one — so the child would
execute release or main-checkout code while `dev run` printed the lane's
origins. `dev run` therefore runs a nested `yoke` as the CLI module on the same
interpreter it just verified. That binding carries through the watcher wrappers
and the gates they wrap, because each of those runs its own child as
`<interpreter> -m <module>`:

```bash
yoke --env <name> dev run -- yoke watch qa-case -- --requirement-id <id>
yoke --env <name> dev run -- yoke migration rehearse PREFIX-N
```

Keep the `yoke watch <kind>` spelling inside that wrapper: the retired
`python3 -m yoke_core.tools.watch_*` form is refused by
`lint-watcher-module-form`, and it is not what binds the lane — the outer
`dev run` is.

Focused pytest normally goes through `yoke watch pytest`, which already binds
the same resolver and enforces the session's verification-tree claim. Use the
general recipe only for a direct invocation that is not covered by a wrapper:

```bash
yoke dev run -- python3 -m pytest path/to/test_file.py
```

Ruff is a locked development dependency. Lint committed, staged, and unstaged
existing Python changes from the session's claimed source checkout with:

```bash
yoke dev ruff-changed --base <ref>
```

Add `--format-check` to also run `ruff format --check`. The command resolves the
merge-base and HEAD SHAs, reads a NUL-delimited diff from that base through the
current staged and unstaged working tree, excludes deleted or otherwise
nonexistent paths, and runs the locked Ruff version without shell path
expansion. An empty result names both SHAs, the working tree, and the checkout
it compared. Do not call a checkout-local `.venv/bin/ruff` path or rely on an
ambient Homebrew install.

The checkout it reads is never the working directory. A harness re-applies a
previous `cd` between tool calls, so a cwd-derived tree can be a different
checkout than the caller means — and a branch diff taken against the wrong
tree is empty, which would otherwise be reported as a clean pass. The tree
comes from the session's claimed lane, or from an explicit `--workdir
<checkout>`; when neither names one, the command refuses instead of guessing
and prints the working directory it declined to use. Every line it prints
names the tree it read, so a result is always attributable to a checkout.

For a changed-test fallback, first list candidates with:

```bash
git diff --name-only --diff-filter=ACMR <base>...HEAD \
  -- ':(glob)**/test_*.py' ':(glob)**/*_test.py'
```

Review the newline-delimited output, then pass the exact existing paths to
`watch_pytest`. Do not pipe NUL-delimited Git output through `rg -z`, and never
feed a filter diagnostic to pytest as a filename.
