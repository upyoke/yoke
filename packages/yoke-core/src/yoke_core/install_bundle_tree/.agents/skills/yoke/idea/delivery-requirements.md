# Idea / Dash — Persist Delivery Requirements At Intake

Called after the item exists and this session holds its work claim
(`infer-and-create.md` §5b, or Dash's post-file claim). Owns the
natural-language request: a screenshot, other deployed evidence, or
"have me approve it". Do not invent a second requirement store, a
per-item flow engine, or a hidden stage model.

## When this applies

Run this when the operator asked for any of:

- a screenshot or visual proof of a running surface
- QA against a named environment (stage, production) or a preview
- an explicit human approval of that evidence

Skip when the request is ordinary implementation work with no delivery
evidence. Pre-merge branch previews stay workflow review/QA; they are not
this path.

## Keep the two QA families apart

| Request | `--qa-phase` | `--target-env` | Do not |
|---|---|---|---|
| Pre-merge preview / implementation check | `verification` | omit, or the pre-merge target | treat it as release proof |
| Deployed merged candidate (stage / prod / release preview) | `post_deploy` | the requested environment name | run it before that target exists; move an existing verification row into release |

A screenshot request specializes the case. It does not clone a flow when
the selected flow's sequence and verdict already fit. `--requirement-source
explicit`. Do not add a second case catalog.

## Select a flow that can satisfy the request

Resolve in this order, without dropping the request:

1. The item's explicit `deployment_flow` when already set.
2. The project's workflow-specific default from
   `yoke workflows mechanics get --json` (`delivery_defaults` for this
   `workflow_id`).
3. The project-wide `yoke project-structure deploy-defaults get --project P`.

Task stays exempt: omit `--deployment-flow` even when an old mapping still
names a flow. Never store the literal `none`.

Read the candidate:

```bash
yoke deployment-flows get FLOW-ID --json
```

Refuse to assign a disabled flow. Before creating or activating a
definition the serving runtime may not execute, validate it:

```bash
yoke deployment-flows validate --project P --stages-file PATH \
  --target-tier persistent --environment ENV --status active --json
```

`execution_supported=false` means keep the definition `--status disabled` and
do not set it as a default or item flow. The refusal
`serving runtime executes through schema N` is the recovery: wait for that
runtime; do not silently pick a weaker flow that drops the request.

When the inherited default cannot satisfy the requested environment, QA, or
verdict, select or configure a suitable active flow for **this item only**:

```bash
yoke items scalar update PREFIX-N --field deployment_flow --value FLOW-ID
```

Do not rewrite `deploy_defaults` or `workflows.delivery_default.set` to make
a single item succeed. Those are shared.

## Persist the item-specific case

Dash's QA policy is optional item attachment. A screenshot Dash must select
the method before `qa.requirement.add` will accept the row:

- at file time: `yoke dash "TITLE" "INSTRUCTION" --execution-instructions-considered --verification-method browser-inspection`
- afterwards: `yoke workflows item-posture amend PREFIX-N --verification-method browser-inspection --reason "intake screenshot request"`

Issue / Epic / Blitz already carry a `qa_verification` gate; do not invent a
Dash-style posture there.

Bind `--workflow-transition` to a stage that currently has a reachable
`qa_verification` gate, or Dash's selected-method review stage. Dash after the
method is selected: `reviewing-implementation`. Issue / Epic / Blitz: the
earliest stage that already carries `qa_verification` (`reviewed-implementation`
on Issue). `--qa-phase` and `--target-env` carry the release vs pre-merge
distinction; do not wait for a future `release` stage to record the request.
If add refuses a missing selector, report that exact field to steering — do
not create a parallel table.

Recording `post_deploy` on that stage stores the obligation. Pre-merge
`qa_verification` and Dash's review gate wait only for `verification` rows.
They do not wait for an environment that exists after merge. Later `done`
(and item-scoped deploy QA) consume `post_deploy`.

Screenshot / visual evidence:

```bash
yoke qa requirement add --item PREFIX-N \
  --method-id browser-inspection --qa-phase post_deploy \
  --target-env ENV \
  --requirement-source explicit \
  --instructions "Capture the requested running surface on ENV." \
  --expected-outcome "The screenshot shows the requested behavior on ENV." \
  --method-config '{"steps":[{"action":"navigate","route":"/ROUTE"},{"action":"screenshot","capture":true,"name":"intake"}]}' \
  --workflow-transition reviewing-implementation
```

Non-visual deployed evidence uses `--method-id command` with the same
`post_deploy` + `--target-env`. Pre-merge visual checks use `--qa-phase
verification` and omit `--target-env` unless a pre-merge target was named.

Read back `yoke qa requirement list --item PREFIX-N --json` and confirm
`qa_phase`, `target_env`, and instructions survived. Intake persists the
obligation; it does not execute the case and it does not create a
deployment run.

## Approval is a flow verdict, not a QA add-on

An evidence-only request does **not** add approval, `--approval-on-done`,
or a human reviewer.

"Have me approve it" requires `verdict.mode=required_human` on the
**item-scoped QA stage** whose `target` is the requested persistent
environment (`scope: item`, `target.kind=persistent_environment`,
`environment: ENV`). That stage's `reviewers` require **this operator**
(`actors` + `mode=all`), not an `ANY` role policy someone else can satisfy,
and not a run-scoped QA stage or a non-QA execution stage. Missing reviewer
policy makes that configuration invalid. `human_if_unsure` can pass
without asking the operator; reserve it for an explicitly conditional
review request ("ask me if you're unsure").

When the selected flow already has a compatible reviewer requirement that
already requires this operator at `required_human` on that environment's
item-QA stage, keep it. Do not replace a matching policy, and do not
weaken `required_human` to `human_if_unsure`.

If the candidate is referenced by a run, immutable history, or a shared
project/workflow default, `yoke deployment-flows create` a new
item-only definition (validate first), then
`yoke items scalar update PREFIX-N --field deployment_flow --value FLOW-ID`.
Never `update-stages` a shared, referenced, or immutable definition. Do not
build a fallback reviewer system.
