# Feed — reconcile owned dependency facts

Visit EVERY in-scope dependent, including those with no inferred edges.
Use `items.dependency.list` via `yoke items dependency list PREFIX-N`;
compare existing rows with Decide's canonical edge contract. Resolve public refs,
rather than constructing internal ids. Mutations require the dependent's
work claim; coordinate live holders.

1. Preserve every non-Feed row. Equivalent compatible manual relation: no
   duplicate Feed row. Different manual gate: preserve manual, omit inferred
   Feed row, record both proposals and resolution.
2. Remove obsolete Feed edges only when every row for that dependent/blocker
   pair is Feed-owned. Registered remove is PAIR-WIDE: if any manual row or
   still-needed gate shares the pair, stop that removal and report selective
   source/gate removal to the control-plane operator. Checked surfaces:
   `items.dependency.remove` and its CLI; neither accepts those selectors.
3. Add missing rows with rationale/full structured evidence. Update Feed-owned
   gate/satisfaction/rationale with the registered match-gate selector.
   Update cannot change evidence_json: changed evidence requires operator
   recovery rather than a fabricated flag or overwriting manual rows.
   The existing add is insert-only on conflict, not evidence replacement.

```sh
yoke items dependency remove PREFIX-N PREFIX-M
yoke items dependency add PREFIX-N PREFIX-M feed --gate-point activation --satisfaction "status:done" --rationale "<why>" --evidence '{"shared_files":["<path>"],"blocker_class":"coding_order","constraint_type":"schema"}'
yoke items dependency update PREFIX-N PREFIX-M --match-gate-point activation --gate-point integration --satisfaction "fact:merged" --rationale "<why parallel coding is safe but merge order matters>"
```

These are alternatives selected after ownership/row inspection, not a sequence.
Use the five gate/satisfaction classes in [decide.md](decide.md); actual
environment run membership remains mandatory. Read command help before writes,
verify each result and release the temporary dependent claim.

Track added/updated/removed/preserved counters and `_edge_mutations.append`
actual action/dependent/blocking/gate_point/satisfaction/source/rationale.

Stale non-Feed cancelled blockers (resolution/absorbed scope) get
`_stale_edges` cleanup/successor recommendations, never automatic deletion.
Satisfied done edges are not inherently stale; an implemented-stage intent
may warrant review. Record manual-vs-Feed conflicts with both gates/satisfactions
and the preservation result.

Read back every scoped dependent: each inferred row exists or was skipped for
manual conflict; zero-edge targets have no obsolete Feed leftovers.
Compare exact rows/counts for idempotency. Mismatches/unsupported operations
enter `_reconcile_errors`; report them without retrying this run.
Carry counters, exact mutations, stale rows, conflicts and errors to summary.
