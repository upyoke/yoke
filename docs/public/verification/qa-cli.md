# QA CLI

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > QA CLI
<!-- /yoke:breadcrumbs -->

Use the registered QA commands to author requirements, execute cases and record evidence. The [database reference](../databases/reference.md) owns the domain catalog and shared payload conventions.

## qa domain CLI

Python owner: `yoke_core.domain.qa`. Public command examples use the installed
Yoke CLI, which dispatches the registered `qa.*` function ids:

- `yoke qa requirement add|add-batch|list|get|update|waive ...`
- `yoke qa plan materialize --item PREFIX-N --transition T`
- `yoke qa plan run --deployment-run-id RUN --stage STAGE [--member PREFIX-N] [--plan PLAN] --project P` — `--plan` only for a stage that names no cases; one already naming its own refuses it
- `yoke qa plan run --deployment-run-id RUN --plan PLAN --project P` — run-wide, and refused on a run pinning any QA stage
- `yoke qa run add|complete|record-verdict|list|get ...`
- `yoke qa artifact presign|add ...`
- `yoke qa gate-summary ...`

All CRUD logic for the `qa_requirements`, `qa_runs`, and `qa_artifacts` tables
lives in `yoke_core.domain.qa`; that module name is implementation authority,
not an agent-facing command recipe. Full platform documentation:
[QA platform](platform.md).

```sh
# Add an item-bound review requirement
yoke qa requirement add \
 --item PREFIX-N --qa-kind implementation_review --qa-phase verification \
 --workflow-transition reviewed-implementation

# Bind a method case to a stage in the item's pinned workflow
yoke qa requirement add \
 --item PREFIX-N --method-id browser-check --qa-phase verification \
 --workflow-transition reviewing-implementation \
 --instructions "Inspect the workflow view." \
 --expected-outcome "The workflow view is correct." \
 --method-config '{"steps":[{"action":"navigate","route":"/workflows"}]}'

# Attach an executable case to a deployment run, optionally scoped to one
# stage and one member item the run carries. No workflow transition: the
# run owns that context. Refused on a finished run.
yoke qa requirement add \
 --deployment-run run-YYYYMMDD-NNN --method-id browser-inspection \
 --qa-phase post_deploy --deployment-stage stage-smoke \
 --deployment-member-item PREFIX-N \
 --instructions "Open the released home route." \
 --expected-outcome "The home page renders the new build." \
 --method-config '{"steps":[{"action":"navigate","route":"/"}]}'

# List requirements
yoke qa requirement list --item PREFIX-N

# Get a single requirement
yoke qa requirement get --requirement-id 1

# Update a mutable field on an existing requirement
yoke qa requirement update --requirement-id 4309 --field blocking_mode --value non_blocking
yoke qa requirement update --requirement-id 4309 --field success_policy --value "$policy_json"
yoke qa requirement update --requirement-id 4309 --field method_config --value "$config_json"

# Record a QA run for that item-bound review requirement.
# Blocking passes stamp verification_tree.head_sha from the claimed lane HEAD
# from the clean lane. --raw-result is evidence text, not the run identity.
yoke qa run add \
 --requirement-id 1 --performed-by agent --qa-kind implementation_review --verdict pass

# Epic-task review verdicts use the workflow-item helper path
yoke workflow-item epic-task review-insert \
 --epic PREFIX-833 --task-num 5 --verdict pass --body "Review passed"

# List runs
yoke qa run list --requirement-id 1

# Materialize and execute a named plan against a real deployment run.
# Name the stage the run is at, plus the member when that stage's scope is
# item: a stage credits only requirements bound to both.
yoke qa plan run \
 --deployment-run-id run-YYYYMMDD-NNN --stage item-qa --member PREFIX-N \
 --plan installer-campaign --project P

# Attach an artifact
yoke qa artifact add \
 --requirement-id 1 --run-id 1 --artifact-type screenshot \
 --artifact-handle '{"backend":"local","path":"/tmp/img.png"}'

# Attach inline screenshot bytes (mutually exclusive with --artifact-handle)
yoke qa artifact add \
 --requirement-id 1 --run-id 1 --artifact-type screenshot \
 --content-type image/png --filename capture.png --content-file PATH

# Preview blocking QA gaps before a reviewed-implementation transition
yoke qa gate-summary --item PREFIX-N --target reviewed-implementation --json
```

| Subcommand | Args | Description |
|---|---|---|
| `yoke qa requirement add` | `--item PREFIX-N (--qa-kind K \| --method-id M) --qa-phase P --workflow-transition STAGE [opts]`, or `--deployment-run RUN --method-id M --qa-phase P [--deployment-stage STAGE [--deployment-member-item PREFIX-N]] [opts]` | Insert one requirement — bound to a QA-gated stage in the item's pinned workflow, or attached to a deployment run (authorized by the run's project scope, no workflow transition, refused on a finished run or a stage/member the run does not declare) |
| `yoke qa requirement add-batch` | `--item PREFIX-N (--rows-file PATH \| --stdin)` | Insert item-attached requirements atomically; every row requires `workflow_transition_id` |
| `yoke qa plan materialize` | `--item PREFIX-N --transition T`, legacy `--deployment-run-id RUN --plan PLAN --project P`, or scoped `--deployment-run-id RUN --stage STAGE [--member PREFIX-N] [--plan PLAN] --project P` | Materialize attached item plans, one run-wide plan (refused when the run pins any QA stage, since every stage counts only rows carrying its own name), or frozen stage/member obligations; each case stays on the shared QA authority. For a stage already naming admitted cases, a correction-only `--plan` is accepted when repeatable `--replaces CASE_KEY=FAILED_REQUIREMENT_ID` names every plan case. Materialization and declaration commit together: the declaration immediately removes predecessor grading; the final effective corrected case blocks until its current attempt passes independent review and proof |
| `yoke qa plan run` | The same item, legacy run, or scoped stage/member selectors as materialize | Execute one server-issued durable roster against its exact subject and target; a run subject also accepts `--replaces` for the cases its `--plan` materializes |
| `yoke qa requirement supersede` | `--requirement-id N --superseded-by-requirement-id N --rationale TEXT` | Discharge a failed case with a passing same-scope corrected case, or retire a post_deploy item source in favor of a corrected item requirement once a passing run case superseded one of its admitted copies (or no run the item still belongs to holds a copy, so the corrected requirement owes its own proof); later releases admit only the corrected body |
| `yoke qa requirement supersede --declare-replacement` | `--requirement-id FAILED_ID --superseded-by-requirement-id CORRECTED_ID --rationale TEXT` | Declare an existing corrected case (a direct run case, or an item case of the same item, transition and phase) as the replacement of a failed one before it passes; the predecessor immediately leaves grading; the scoped runner grades the final corrected blocking case, and its current qualified pass records the passing-supersession audit. |
| `yoke qa requirement list` | `[--item PREFIX-N \| --epic PREFIX-N \| --deployment-run-id ID]` | List requirements |
| `yoke qa requirement get` | `--requirement-id N` | Get one requirement |
| `yoke qa requirement update` | `--requirement-id N --field FIELD (--value VALUE \| --null)` | Update one mutable field |
| `yoke qa requirement waive` | `--requirement-id N --rationale TEXT [--source operator\|agent] [--force]` | Waive a requirement with a recorded rationale |
| `yoke qa run add` | `--requirement-id N --performed-by T [--qa-kind K] [--verdict V] [opts]` | Insert an actual run; code/build blocking passes bind observed commit identity, while Machine and endpoint cases retain their actual subject proof |
| `yoke qa run complete` | `--requirement-id N --run-id N [--verdict V] [--execution-status captured\|capture_failed] [opts]` | Complete a previously recorded run |
| `yoke qa run record-verdict` | `--requirement-id N --performed-by T --verdict V [opts]` | Record a one-shot verdict |
| `yoke qa run list` | `[--requirement-id N]` | List runs |
| `yoke qa run get` | `--run-id N [--project P]` | Get one run |
| `yoke qa artifact presign` | `--requirement-id N --run-id N --filename NAME [--content-type CT]` | Mint a durable upload target |
| `yoke qa artifact add` | `--requirement-id N --run-id N --artifact-type T (--artifact-handle JSON \| --content-base64 B64 --filename NAME \| --content-file PATH) [opts]` | Insert an artifact row from a typed handle or inline bytes |
| `yoke qa gate-summary` | `(--item PREFIX-N \| --epic PREFIX-N --task-num K) --target reviewed-implementation\|implemented` | Read blocking QA gaps for a transition |

No public QA init or artifact-list adapter is registered. Schema
initialization belongs to DB setup/migrations. Artifact-list remains an
implementation/domain capability until a public adapter is registered; do
not teach a fake public listing command for it. `yoke qa requirement waive`
and `yoke qa run get` are registered public adapters.

**When to use which mutator.** `requirement-update` changes the *policy* or
*executable config* of an existing requirement — tighten a success policy,
move a requirement between `blocking` and `non_blocking`, bind it to a
different `target_env`, correct a live `method_config` capture script
(selectors, waits, assertions), or clear a nullable field. It preserves the
requirement identity, so linked runs and artifacts stay attached. A
`method_config` correction invalidates prior greens for gating unless a later run recorded the new config at start; re-run the
case. Frozen deployment-run requirements refuse `method_config` updates.
Use `requirement-add` when the *verification surface itself* needs to change
— for example, swapping from `unit_test` to `integration` — since that is a
different requirement. `requirement-update` refuses to mutate `qa_kind` for
exactly that reason. It cannot change `instructions` or `expected_outcome`
either: a post_deploy item source worded wrong is corrected by adding the
corrected requirement and retiring the source with `yoke qa requirement
supersede` after a passing run case answered its failed admitted copy, or
once no run the item still belongs to holds a copy.
Recording a requirement never checks the runtime against `--target-env`;
only executing the case does.

Exit codes: 0 = success, 1 = error/not found, 2 = usage error

## Related

- [QA model](model/qa.md)
- [Body write path](../items/model/body-writes.md)
