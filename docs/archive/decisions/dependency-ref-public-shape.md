---
slug: dependency-ref-public-shape
retired-without-apply: false
affected-tables:
  - item_dependencies
related-migration-module: item_dependency_public_ref_repair
---

# Decision: `item_dependencies` ref columns hold public item refs

## Context

`item_dependencies.dependent_item` and `item_dependencies.blocking_item` are
`TEXT` columns. They store a **public item ref** — the string
`projects.public_item_prefix || '-' || items.project_sequence`. They do not
store `items.id`, and they are not the numeric-`item_id` surface the rest of
the schema uses.

Two facts make a wrong value hard to see:

1. **The two numbers coincided for a long time.** For every item created up to
   a certain point, `items.id` and `items.project_sequence` were equal, so a
   ref built from the internal id was byte-identical to the correct public
   ref. The two readings only diverge once a project's sequence and the global
   id counter drift apart, which happens as soon as more than one project
   allocates items.
2. **The prefix was hardcoded.** A ref built as `'YOK-' || items.id` is wrong
   for every item that does not belong to the project whose prefix is `YOK`,
   but it still *looks* like a well-formed ref.

The result is two malformed shapes in the live data:

- **Wrong prefix.** An item belonging to another project stored under the
  `YOK` prefix. The value resolves to nothing, so the edge is invisible to a
  strict public-ref reader.
- **Wrong number.** An item whose `project_sequence` has diverged from its
  `items.id` stored under its internal id. Today the value resolves to
  nothing; once the project's sequence counter passes that number, the same
  string resolves to a *different, unrelated* item and the error becomes
  silent.

The second shape is the reason this is not cosmetic. A dangling ref is
detectable; a ref that quietly points at the wrong item is not.

## Decision

The repair is expressed as a governed migration module,
`item_dependency_public_ref_repair`, and it infers intent from data rather
than from a list of known-bad rows. For every non-empty value in either ref
column:

| Resolves as public ref | Numeric tail resolves as `items.id` | Action |
|---|---|---|
| yes | — | leave untouched |
| no | yes | rewrite to that item's true public ref |
| no | no | leave untouched, report |
| yes | yes, but a *different* item | leave untouched, report loudly |

Data-driven rather than row-keyed, because the writer that produced the
malformed values stays live until the reader/writer cutover lands, so the
affected population can grow between authoring and apply. Two guards bound
that openness: a rewrite set larger than `MAX_REWRITES` aborts the apply
before any write, and a rewrite that would collapse two distinct edges onto
the same `(dependent_item, blocking_item, gate_point)` unique key is refused
with the colliding ids named.

Nothing is guessed. A value that resolves under neither reading names an item
that no longer exists; no public ref can be derived for it, so it is reported
and carried forward. A value that resolves both ways names two different
items, and no rule can say which the author meant.

## Consequences

**Invariant.** The module's `invariants(conn)` hook asserts that no stored ref
resolves *only* as an internal item id. That is exactly the property the
repair establishes: every value either matches a public ref or resolves under
neither reading. The genuinely orphaned values are the documented allowance —
they are not evidence of a failed repair, so the hook does not fail on them.

**Ordering is load-bearing.** Several live readers resolve these columns with
`CAST(REPLACE(col, 'YOK-', '') AS INTEGER)` — among them
`dependency_planning`, `dependencies`, `shepherd_dependency_enrich`,
`path_claim_hard_block_review`, `deployment_runs_validation`, and the
cancelled-blocker health check. Every stored value carries the `YOK` prefix
today, so those casts succeed. Introducing a non-`YOK` prefix makes the cast
raise `invalid input syntax for type integer` for the whole batch query, not
just for the repaired row; and remapping a `YOK`-prefixed value whose sequence
diverges from its internal id makes those same readers resolve the edge to the
wrong item. **The repair must therefore be applied only after the public-ref
reader and writer cutover is merged and deployed to the authority it targets.**
The migration is declared `pre_merge_breaking` for exactly this reason.

**Row count is preserved.** The migration only rewrites column values;
`item_dependencies` gains and loses no rows, and a second run is a no-op.
