# Steer — resolve the document and take the paired seat

The slug is the operator's, else `CURRENT-PLAN`; never ask. Repeat per project.

```text
yoke projects checkout-context --field slug
yoke strategy doc get {SLUG} --project {_project}
yoke claims steering acquire --project {_project} --plan-doc {SLUG} --reason "steer {SLUG}"
```

Read the doc before acting. Keep its cold-start refresh, decisions, holds,
gates and open-work index in the plan:
In flight / Ready to staff / Blocked / Awaiting operator decision.

Use `--doc` instead of `--plan-doc` when the operator named a document. Proceed
only with both halves held. Read all inherited mail and answer it before the
first pass.

A missing doc (not a failed read): offer to create it and wait for a yes; no means stop.
The seed uses headings `# Objective`, `# Frontier`, `# Decisions`, `# Gates`.

```text
yoke strategy doc create {SLUG} --summary "Document purpose" --state draft --stdin --project {_project} < SEED_FILE
```

Next: [watching.md](watching.md), then [loop.md](loop.md).
