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
session_id INTEGER -- nullable contextual session ID
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

The writer uses idempotent `ON CONFLICT DO NOTHING` for the unique edge.

### Canonical blocker model

Activation, integration and closure edges have directional meaning: the dependent cannot pass that gate until the blocker satisfies the condition. Coordination-only edges are excluded from blocker evaluation.

**Gate point** (`gate_point`) -- *when* in the dependent's lifecycle the dependency is enforced:
- `activation` -- do not start the dependent yet (checked before advancing to `implementing`)
- `integration` -- may work in parallel, but the dependent must land (merge) after the blocker
- `closure` -- the dependent may not close before the blocker satisfies its condition
- `coordination_only` -- attested independent overlap; no lifecycle wait

**Satisfaction condition** (`satisfaction`) -- *what* must be true about the blocker:
- `status:<stage-id>` -- blocking item must reach that stage in its pinned workflow. Use `status:done` for the usual item-to-item wait, including required deployment and closeout. Authoring a stage that workflow version does not have refuses and lists the stages it does
- `fact:merged` -- blocking item's merge must be confirmed by canonical fact (`merged_at`), branch ancestry when available, or `release`/`done` status as the weakest fallback
- `fact:deployed:<environment-name>` -- the blocker must be done and its delivery stamp must attribute completion to that registered environment. The persisted attribution names the exact run, member, environment, project and candidate, including source-bound cross-project delivery. Readers never re-check current whole-run status or QA acceptance; subsequent sibling failure or cancellation leaves completed delivery satisfied. Ordinary completion dependencies use `status:done` and ignore run and environment.

**Explanation fields**:
- `rationale` -- short human-readable reason for the edge (e.g., "Operator-declared activation dependency")
- `evidence_json` -- structured evidence/provenance payload (e.g., `{"created_by":"operator"}`)

**Evaluation owner:** `yoke_core.domain.dependency_planning` shares single-item
gate evaluation, batched frontier evaluation and topologically ordered
candidate planning. Registered readers return structured blockers; internal
Python service clients are not an agent recipe.

**Enforcement:** `evaluate_blockers` (`python3 -m yoke_core.domain.check_hard_blocks`, optional `--gate-point`) is the one evaluator. `implement` / `conduct` / `usher` share it. The authoritative status write runs it for listed `check_hard_blocks` at `activation`, and on every write to `done` at `closure` (not skippable by force or QA bypass). `items.block` refuses a wait a live activation/integration/closure edge already carries — use `yoke items dependency add`. The frontier uses `evaluate_batch_gates()` for activation.

## Related

- [Item model](items.md)
- [Generated task model](tasks.md)
