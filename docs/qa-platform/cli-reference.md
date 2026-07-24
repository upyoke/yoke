# QA CLI Reference

The QA platform exposes public Yoke CLI adapters for registered `qa.*`
function ids. The implementation still lives in modules such as
`yoke_core.domain.qa` and `yoke_core.domain.qa_gates`, but those module
names are code references, not command recipes.

Cross-link back from [qa-platform.md](../qa-platform.md) for the four-layer
model, table schemas, success-policy types, and gating semantics that this CLI
reads and writes. See [`.yoke/docs/db-reference/functions.md`](../db-reference/functions.md)
for the function-call envelope and [`docs/atlas.md`](../atlas.md) for the
operator-readable Atlas of registered surfaces.

## Public QA Commands

```sh
# Add an item-bound review requirement
yoke qa requirement add \
 --item YOK-N --qa-kind implementation_review --qa-phase verification \
 --blocking-mode blocking --requirement-source explicit \
 --success-policy '{"type":"deterministic","criteria":"verdict_pass"}'

# Add multiple item-bound requirements
yoke qa requirement add-batch --item YOK-N --rows-file qa-requirements.json

# Let project/item policy materialize defaults
yoke qa requirement auto-create-for-item --item YOK-N

# List requirements for an item, epic, or deployment run
yoke qa requirement list --item YOK-N
yoke qa requirement list --epic-id 833 --json
yoke qa requirement list --deployment-run-id run-20260616-001 --json

# Get or update a single requirement
yoke qa requirement get --requirement-id 1
yoke qa requirement update --requirement-id 1 --field blocking_mode --value non_blocking

# Record or complete QA runs
yoke qa run add \
 --requirement-id 1 --executor-type agent --qa-kind implementation_review \
 --verdict pass --raw-result "Tester review passed"
yoke qa run complete \
 --requirement-id 1 --run-id 10 --verdict pass --execution-status completed
yoke qa run record-verdict \
 --requirement-id 1 --executor-type agent --verdict pass

# List runs for a requirement
yoke qa run list --requirement-id 1

# Attach durable or explicit local artifacts
yoke qa artifact presign --requirement-id 1 --run-id 10 --filename screenshot.png
yoke qa artifact add \
 --requirement-id 1 --run-id 10 --artifact-type screenshot \
 --content-type image/png \
 --artifact-handle '{"backend":"local","path":"/tmp/screenshot.png"}' \
 --metadata '{"width":1920,"height":1080}'
```

| Command | Args | Description |
|---|---|---|
| `yoke qa requirement add` | `--item PREFIX-N --qa-kind K --qa-phase P [opts]` | Insert one item-attached requirement |
| `yoke qa requirement add-batch` | `--item PREFIX-N (--rows-file PATH \| --stdin)` | Insert item-attached requirements atomically |
| `yoke qa requirement auto-create-for-item` | `--item PREFIX-N` | Materialize policy/default requirements |
| `yoke qa requirement list` | `[--item PREFIX-N \| --epic-id N \| --deployment-run-id ID]` | List requirements |
| `yoke qa requirement get` | `--requirement-id N` | Get one requirement |
| `yoke qa requirement update` | `--requirement-id N --field FIELD (--value VALUE \| --null)` | Update one mutable field |
| `yoke qa run add` | `--requirement-id N --executor-type T [--qa-kind K] [--verdict V] [opts]` | Insert a started or completed run |
| `yoke qa run complete` | `--requirement-id N --run-id N [--verdict V] [--execution-status S] [opts]` | Complete a previously recorded run |
| `yoke qa run record-verdict` | `--requirement-id N --executor-type T --verdict V [opts]` | Record a one-shot verdict |
| `yoke qa run list` | `[--requirement-id N]` | List runs |
| `yoke qa artifact presign` | `--requirement-id N --run-id N --filename NAME [--content-type CT]` | Mint a durable upload target |
| `yoke qa artifact add` | `--requirement-id N --run-id N --artifact-type T --artifact-handle JSON [opts]` | Insert artifact evidence |

Exit codes follow the Yoke CLI envelope: 0 = command dispatched successfully,
1 = dispatch/not-found failure, 2 = usage error.

## Missing Public Adapters

These implementation capabilities exist below the public CLI boundary, but no
registered `yoke qa ...` adapter is present in this branch:

| Missing adapter | Disposition |
|---|---|
| QA init | Schema setup belongs to DB initialization/migrations, not a public QA adapter |
| Requirement waiver | Do not teach a command recipe until a waiver adapter is registered |
| Single-run get | Use `yoke qa run list --requirement-id N` for public reads, or add a wrapper if single-run fetch becomes product surface |
| Artifact list | Artifact reads need a registered wrapper before docs should teach them |

Public requirement creation is item-scoped. Epic-task and deployment-run
requirements are materialized by their owning lifecycle/deployment flows; the
public read surface can list them with `--epic-id` or `--deployment-run-id`.

## Gate Summary

`yoke qa gate-summary` is the public, read-only preview for QA gate state.
It wraps the same satisfaction semantics used by the lifecycle gates without
teaching internal `qa_gates` commands.

```sh
# Preview verification-phase gaps before reviewed-implementation
yoke qa gate-summary --item YOK-N --target reviewed-implementation --json
yoke qa gate-summary --epic-id 833 --task-num 5 --target reviewed-implementation

# Preview blocking requirements across phases before the implemented handoff
yoke qa gate-summary --item YOK-N --target implemented --json
```

| Command | Returns | Description |
|---|---|---|
| `yoke qa gate-summary --target reviewed-implementation` | JSON/text summary; exit 0 when dispatch succeeds | Shows blocking verification requirements that still lack satisfying evidence |
| `yoke qa gate-summary --target implemented` | JSON/text summary; exit 0 when dispatch succeeds | Shows blocking requirements across phases that still lack satisfying evidence |

**Argument format:**

- Item: `--item PREFIX-N` (for example, `--item YOK-N`)
- Epic task: `--epic-id N --task-num K` (for example, `--epic-id 833 --task-num 5`)

**Environment:**

- `YOKE_QA_GATE_BYPASS` -- internal lifecycle bypass for force operations
- `YOKE_SKIP_SIMULATION` -- internal lifecycle bypass for the epic simulation gate only
