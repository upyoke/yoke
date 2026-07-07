# `items.body` is a virtual rendered field

## Context

An earlier version of the backlog stored item bodies as raw Markdown in a
dedicated `body` column on the `items` table. Two pressures made that model
painful to maintain:

1. Writers had to keep structured fields (`spec`, `design_spec`,
   `technical_plan`, `worktree_plan`, `shepherd_log`, `shepherd_caveats`,
   `test_results`, `deploy_log`) in sync with the mirror inside the raw
   body. Any divergence masked real content.
2. Every edit path needed to know about section layout and separators, so
   the "one canonical source" contract drifted. Each new writer re-invented
   section boundaries slightly differently.

## Decision

`items.body` is a **virtual rendered field**. The DB stores only the
structured fields listed above; `body` is reconstructed on demand by
`runtime.api.domain.render_body.build_body()`.

- Reads: `python3 -m runtime.api.cli.db_router items get YOK-N body` renders
  the body from the structured fields at query time.
- Writes: raw body writes are unsupported. Content flows through structured
  fields only; `items update <id> <field>` with `--stdin` is the canonical
  entry point.

## Consequences

- Health checks and linters that previously compared a stored body against
  the structured fields are gone — the rendered body cannot drift from its
  source because it is computed, not stored.
- Section helpers live in `runtime.api.cli.db_router sections` for surgical
  edits of named sections inside a structured field. Body-wide mutations go
  through the owning structured field.
