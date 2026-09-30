# Dash phase 4 — execute the instruction

Make the smallest complete change. Preserve unrelated work. Apply the
repository's simplify doctrine and governed database rules. Run focused
checks while editing. Capture every non-trivial test or build before
inspecting its tail.

## Two checks that cost seconds

Run both before you commit, so verification meets no failure the lane could
have answered:

```text
yoke dev import-check <module> [<module> ...]
yoke dev ruff-changed --base <base-branch> --fix-format
```

`import-check` imports the modules you added or moved and names the file that
answered each one — a circular import, a missing dependency, or module-level
code that raises surfaces here instead of in test collection.

`--fix-format` writes the formatting over the same changed-path set the
required CI contract checks, then lints the formatted result. Use it rather
than `--format-check`, which only reports the reformatting you would then have
to apply by hand. Commit the formatting it writes.

Size is not a reason to leave Dash. Plan, coordinate across files, and
implement in as many incremental steps as the instruction needs — all here.
The operator chose this workflow; never propose another because the work
turned out large.

## A grounded no-change finding

If the instruction is investigative, the durable result may be a
well-grounded no-change finding. Do not invent a code change merely to
produce a diff. Record that exact outcome with
`yoke direct-workflow dash survey ITEM --no-changes --json` wherever the
sequence requires the actual touch set; never substitute a placeholder.

When that survey is recorded, still run worktree prepare: the engine skips
the git lane, dependency install, and upstream isolation (`worktree:skipped`).
That skip is survey evidence, not `worktrees=none`. If the finding later
needs edits, replace the survey with the real paths first, then re-run
prepare so isolation happens before any edit. Do not invent SHAs, CI, a
merge, or a deploy. Close through the laneless route in
[`close-out.md`](close-out.md). Keep required QA, approvals, and delivery
policy; empty optional Dash QA/delivery is the existing close-out repair.

Next: [`verify.md`](verify.md).
