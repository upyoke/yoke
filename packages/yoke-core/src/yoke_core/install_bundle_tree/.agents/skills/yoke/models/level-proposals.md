# Model Level Proposals

`yoke models level-proposal` reads current catalog and universe levels.
Superseded model rows move to their successors in place; unpublished minimum
effort moves to the nearest published effort. Rows contain only model and
min_effort, without native surfaces, context or exhausted-pool fallbacks.

The proposal prints each level as `model min_effort` rows and names
unverified model/effort facts, unplaced current models (placeable, with
published efforts) and unplaceable ones (the catalog publishes no efforts, so
no row can name them).
Use researched facts to author adds, moves, retirements and threshold changes:

```json
{"kind":"add","level":"SENIOR","option":{"model":"...","min_effort":"medium"},"position":0,"reason":"..."}
{"kind":"move","option":{"model":"...","min_effort":"medium"},"to_level":"JUNIOR","reason":"..."}
{"kind":"retire","option":{"model":"...","min_effort":"medium"},"reason":"..."}
{"kind":"change","option":{"model":"...","min_effort":"medium"},"min_effort":"high","reason":"..."}
```

Thresholds must strictly increase within each model as levels rise. Proposal
and Levels set refuse published-effort contradictions as
`level_min_effort_unpublished`. Present the complete proposal and obtain
operator approval before changing stored Levels.

When `equals_shipped_defaults` is true, approve with `yoke settings unset
levels`: the universe stores nothing and keeps following shipped defaults.
Otherwise store the document, and tell the operator that a stored document
stops following future shipped defaults until `yoke settings unset levels`:

```sh
yoke models level-proposal --levels-only --stdin < changes.json > /tmp/levels.json
yoke settings set levels - < /tmp/levels.json
```

`set` with a document equal to the shipped defaults also stores nothing.
