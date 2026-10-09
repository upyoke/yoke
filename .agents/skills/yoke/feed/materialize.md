# Feed — update and materialize

Only this phase writes item content. Skip to Reconcile with empty
`_updated_items`, `_materialized_items`, `_sharpen_recommendations` only when
updates are empty, decision is leave/refresh, AND materialize/sharpen arrays empty.

## A. Update stale fields first

Acquire each affected item's work claim before writes; coordinate another
live holder rather than borrowing its claim. Prefer the matching structured field:
`items.structured_field.replace` with item public_ref target and
`{field, content, source: "feed"}`; exact envelope:
[Idea's field authority](../idea/body-and-sync-functions.md).
Operator/debug adapter:
`printf '%s\n' "<updated field content>" | yoke items structured-field replace PREFIX-N --field <field> --source feed --stdin`
(`items.structured_field.replace`).

Body is virtual. Fold changed ACs into their owning field; explicitly state
subsumed/invalidated scope. Read effective generated-children posture before
using graph fields; none prohibits worktree_plan/shepherd_caveats/shepherd_log.
If scope was absorbed, do NOT auto-cancel it inside feed; recommend cancellation
with absorbed-by evidence, skipping writes only when cancellation is truthful.
Read back each updated field, then `_updated_items.append` public ref/title,
fields_updated, reason, recommend_cancel and applicable cancellation_reason.
Release the temporary item claim when its mutations/verification finish.

## B. Materialize new work

### 3A.1 Dedup

Use registered `yoke items search "<distinctive keywords>" --project <project>`
with 2–3 distinctive keyword variants; compare non-terminal intent/scope.
Duplicate: record SKIPPED/title/sml_source/skip_reason naming the existing ref,
then continue.

### 3A.2 Resolve The Filing Contract

Resolve project and workflow before final title/body context.
Instruction-led work is Dash regardless of size; agreed ACs/generated task
graphs use eligible Issue/Epic policy. The laneless merge-free floor is Task.

Registered `workflow.execution_instruction.resolve`:

```sh
yoke workflow execution-instruction resolve --workflow <workflow> --project <project> --full
```

Apply every returned instruction to title, instruction, provenance and body
BEFORE final authoring/creation, rather than relying on the create receipt.

### 3A.3 Create via `/yoke idea`

For agreed AC/spec/generated graph, invoke `/yoke idea --workflow ${_workflow}`
inline by reading/following its SKILL.md in this agent. Supply strategic
body_context, pull-forward justification and mandatory provenance:

```markdown
## Strategic Provenance
- **SML Source:** <strategy file/section>
- **Materialized by:** /yoke feed
- **Rationale:** <why ready now>
```

Idea owns title_max_length, inference, secondary dedup, GH sync and AC normalization.
For one coherent instruction carrying all strategic context, file instead:

```sh
yoke dash "<title>" "<instruction including strategic provenance>" --execution-instructions-considered --json
yoke task "<title>" "<instruction including strategic provenance>" --execution-instructions-considered --json
```

Choose one adapter. Dash files without execution at idea/next_step=dash.
Task is only laneless/merge-free, with no optional verification/path-claim/
approval/deployment posture; use Dash when any of those or a git lane is needed.

Record each creation in `_materialized_items` (public ref/title/sml_source);
record duplicate/rejection as SKIPPED with reason. Verify existence and provenance
before the next item. One at a time; if >5 candidates, pause after first 3 and
reassess whether remaining work is ready or belongs in the SML.

## C. Sharpen recommendations

Record public ref/action/recommendation/rationale. Split names distinct scopes
and titles; refine names missing concrete information; add_spec names needed
content; add_ac proposes measurable ACs. This branch recommends rather than
mutating existing items or invoking Refine/Shepherd. No-new suppresses all
creates/splits; full mode permits creates only when explicitly decided.
