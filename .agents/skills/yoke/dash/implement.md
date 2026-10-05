# Dash phase 4 — execute the instruction

Make the smallest complete change. Preserve unrelated work. Apply the
repository's simplify doctrine and governed database rules. Run focused
checks while editing. Capture every non-trivial test or build before
inspecting its tail.

## Yoke source Python checks

Only on a claimed Yoke source lane with changed Python, run these checks
before you commit. These source-development commands resolve Yoke's own
packages and claimed source checkout:

```text
yoke dev import-check <module> [<module> ...]
yoke dev ruff-changed --base <base-branch> --fix-format
```

Run `import-check` for modules you added or moved; skip it when there are none.
It imports those modules and names the file that
answered each one — a circular import, a missing dependency, or module-level
code that raises surfaces here instead of in test collection.

`--fix-format` writes the formatting over the same changed-path set the
required CI contract checks, then lints the formatted result. Use it rather
than `--format-check`, which only reports the reformatting you would then have
to apply by hand. Commit the formatting it writes.

For other projects, run their own declared lint, format, and import smoke
checks from the project rules and lane run recipes. A change with no Python
does not need the Yoke source Python checks; use the project's checks for the
files that changed.

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
