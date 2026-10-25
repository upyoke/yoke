# Item dependency model

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Items](../index.md) > Item dependency model
<!-- /yoke:breadcrumbs -->

Read dependency edges, gate satisfaction and the canonical blocker model.

## Table: item_dependencies

**Inter-item edge authority.** Use `yoke items dependency add` and `yoke items dependency list`; read their `--help` before authoring. Activation, integration and closure edges enforce directional waits. `coordination_only` records an attested independent-overlap decision and does not block. Claims/dependency reconciliation lives in [path-claims.md](../../sessions/model/path-claims.md).

```sql
id INTEGER PRIMARY KEY
dependent_item_id INTEGER NOT NULL REFERENCES items(id)
blocking_item_id INTEGER NOT NULL REFERENCES items(id)
gate_point TEXT NOT NULL DEFAULT 'activation' -- activation | integration | closure | coordination_only
satisfaction TEXT NOT NULL DEFAULT 'status:done' -- status:<stage-id> | fact:merged | fact:deployed:<environment-name>
source TEXT NOT NULL -- shepherd | conduct | operator | migration | feed | idea | refine | dash
session_id TEXT -- nullable; the session that added or last changed the edge
rationale TEXT NOT NULL DEFAULT '' -- human-readable explanation of the edge
evidence_json TEXT NOT NULL DEFAULT '{}' -- structured provenance payload
created_at TIMESTAMPTZ NOT NULL
UNIQUE(dependent_item_id, blocking_item_id, gate_point)
```

Storage is integer foreign keys to `items.id`. Public `PREFIX-N` remains
the API and display token (`yoke items dependency list PREFIX-N`
projects `direction` / `other_item`). Cross-project edges store the
counterpart's internal id and still list as that project's prefix.

Indexes:
- `idx_id_dependent ON item_dependencies(dependent_item_id)`
- `idx_id_blocking ON item_dependencies(blocking_item_id)`

`yoke items dependency add` on an existing edge updates it in place (source, rationale,
satisfaction, evidence) and replies with the stored row: `created dependency #N`,
`updated existing dependency #N: <field> old -> new`, or `unchanged: existing dependency #N`.
`update` also accepts `--source` and `--evidence`. Updates preserve `created_at`; to wait for another landing after an already satisfied edge, remove that edge and add a new one before the next landing.

### Canonical blocker model

Activation, integration and closure edges have directional meaning: the dependent cannot pass that gate until the blocker satisfies the condition. Coordination-only edges are excluded from blocker evaluation.

**Gate point** (`gate_point`) -- *when* in the dependent's lifecycle the dependency is enforced:
- `activation` -- do not start the dependent yet (checked before advancing to `implementing`)
- `integration` -- may work in parallel, but the dependent must land (merge) after the blocker
- `closure` -- the dependent may not close before the blocker satisfies its condition
- `coordination_only` -- attested independent overlap; no lifecycle wait

**Satisfaction condition** (`satisfaction`) -- *what* must be true about the blocker:
- `status:<stage-id>` -- blocking item must reach that stage in its pinned workflow. Use `status:done` for the usual item-to-item wait, including required deployment and closeout. Authoring a stage that workflow version does not have refuses and lists the stages it does
- `fact:merged` -- a blocker at `done` satisfies the edge regardless of its age. For an unfinished blocker, its recorded landing (`merged_at`) must be strictly after this edge's `created_at`; earlier landings, branch ancestry and other lifecycle statuses do not clear the wait
- `fact:deployed:<environment-name>` -- the blocker must be done and its delivery stamp must attribute completion to that registered environment. The persisted attribution names the exact run, member, environment, project and candidate, including source-bound cross-project delivery. Readers never re-check current whole-run status or QA acceptance; subsequent sibling failure or cancellation leaves completed delivery satisfied. Ordinary completion dependencies use `status:done` and ignore run and environment.

**Explanation fields**:
- `rationale` -- short human-readable reason for the edge (e.g., "Operator-declared activation dependency")
- `evidence_json` -- structured evidence/provenance payload (e.g., `{"created_by":"operator"}`)

**Evaluation owner:** `yoke_core.domain.dependency_planning` shares single-item
gate evaluation, batched frontier evaluation and topologically ordered
candidate planning. Registered readers return structured blockers; internal
Python service clients are not an agent recipe.

**Enforcement:** `advance.preflight.hard_blocks` exposes the shared `evaluate_blockers` evaluator through `yoke advance preflight hard-blocks PREFIX-N --gate-point activation`. It evaluates on the selected control plane over HTTPS or local Postgres. `implement` / `conduct` / `usher` share it. The authoritative status write runs it for listed `check_hard_blocks` at `activation`, and on every write to `done` at `closure` (not skippable by force or QA bypass). `items.block` refuses a wait a live activation/integration/closure edge already carries — use `yoke items dependency add`. The frontier uses `evaluate_batch_gates()` for activation.

**Loop refusal:** `items.dependency.add` and `items.dependency.update` (when it changes the gate or satisfaction) refuse with `dependency_cycle` a write that would leave unsatisfied activation/integration/closure edges among live items in a loop, because no item in it could move first. The refusal names every edge in the loop with its id, the items it would strand, and the recovery: make one edge `coordination_only` (`yoke items dependency update DEPENDENT BLOCKING --match-gate-point GATE --gate-point coordination_only --rationale TEXT`), or route the ordering decision to steering. Nothing is written. `coordination_only` edges, satisfied edges and terminal dependents never count. `yoke_core.domain.dependency_cycles` is the one detector: `frontier.list` and `charge.schedule` serve its loops as `dependency_cycles`, the fleet watch raises `fleet ALARM deadlock`, and the steering report lists them under dependency deadlocks.

## Related

- [Item model](items.md)
- [Generated task model](tasks.md)
