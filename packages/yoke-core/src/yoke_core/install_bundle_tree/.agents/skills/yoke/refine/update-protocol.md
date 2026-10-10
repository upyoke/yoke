# Refine — Apply, Verify, Advance

## 6. Enhance only

Read the selected field, identify critique gaps, append sections/ACs/discovery
and analysis; grammar edits may not change meaning. Use registered typed
writes described in [the envelope home](../idea/body-and-sync-functions.md):
- `items.structured_field.append_addendum`: idempotent heading-led addition,
  guarded current read/write/readback; rejects empty, shrinkage or freeze violations.
- `items.structured_field.section_upsert` / `section_append`: targeted additive
  transforms preserving surrounding content.
- `items.structured_field.replace`: entire intended content authored and
  preservation checked; full-field examples use replace.

```bash
yoke items structured-field replace "$ITEM_REF" --field spec --source refine --stdin
yoke items structured-field append-addendum "$ITEM_REF" --field spec --heading "<addition-heading>" --source refine --stdin
yoke items progress-log append "$ITEM_REF" --headline "<current-state>" --source refine --stdin
```

Never read a field into shell, transform and pipe it back; dedicated transforms
own that operation. The audited lint token `lint:no-structured-transform-check`
does not make routine bypass appropriate. Body is virtual; no raw body writes.
Use structured fields or registered item sections. Absolute script paths and
per-call variables avoid lost shell context.

**Subtraction detection before every write:** compare to the original.
Any missing or materially changed decision, AC, user question, evidence,
observation or numbered item rejects the write. Restore it first.
Encode all critique discovery, cleanup, recovery and open-question findings,
not just wording. Major verified errors/contradictions/scope conflicts stop
the write and advance; operator resolves while item stays active.

**File Budget escalation:** when enabled, unresolved file shape,
300+ responsibilities without a clear split, or multi-responsibility tasks
need exact files/counts and options: investigate/split, justified budget
expansion, operator scope change or item split. Never silently advance.
A single verified missing live owner in the same project/target/behavior scope
is an obvious repair: add budget row and widen only if claims enabled.
Multiple plausible owners, changed scope or ambiguous overlap escalates.
Use served scope/stage bindings; do not reconstruct them from a workflow name.

Route spec/design/technical intent to their corresponding fields; worktree_plan
and shepherd_caveats are graph fields only under generated task policy.
Long execution state uses `items.progress_log.append`, which preserves entries
and stamps its own UTC header; never shell-transform/re-upsert the log.
Normalize existing AC labels without substance loss; add canonical
`- [ ] AC-N: ...` and a missing Acceptance Criteria section from stated outcomes.

## 7. Verify every write

Re-read the exact live field after each write. Check preserved intent,
canonical ACs, discovery/residue, cleanup and error coverage.
If empty/malformed, re-read live state before deciding the write failed,
then retry once before reporting failure. Unclear status/write responses
require a fresh DB read, never an assumed failure or duplicate mutation.

When ITEM_NEXT_SKILL=blitz, follow [blitz-execution-document.md](blitz-execution-document.md)
after artifact verification and before advance. `strategy.execution.link`
must read back the exact document; missing/ambiguous/conflicting projection
blocks. Linking metadata does not acquire its execution claim.

## 8. Capture the report

Retain fields updated, actual change count and purpose before status
advancement. Do not emit success yet. Complete [closure.md](closure.md) first.

## 9. Advance through the exact pin

Use `lifecycle.transition.execute` with the active/target statuses:
```bash
yoke lifecycle transition "$ITEM_REF" --from "$REFINE_ACTIVE_STATUS" --to "$REFINE_TARGET_STATUS" --reason "Refinement verified"
```

Refresh item detail and derive next_skill_id with
[shared handoff](../shared/stage-handoff.md); do not reuse entry's prediction.
GitHub body sync is implicit; no repeated sync. Failure leaves the actual
active stage and names repair.

For GATE_DB_CLAIM_PROSE_MISMATCH, amend honestly before retry:
```bash
yoke db-claim amend "$ITEM_REF" --reason "<verified-mutation-or-reviewed-none-reason>" --stdin
```

`db_claim.amend` takes one flat unified profile+attestation. Actual governed
work declares it; meta governance-only prose supplies state:none with
reviewed-none rationale. Never scrub/backtick DDL to evade the gate.
Apply intent requires migration_strategy; pre_merge_readers_writers roles
are reader/writer only, with schema modules as writers.
Read the [DB reference](../../../../.yoke/docs/reference/db-reference.md),
verify amendment and retry the pinned transition.

## 10. Release before success

`claims.work.release` targets the actual claim_id from acquire or holder_get,
with reason **"completed"**:
```bash
yoke claims work release --item "$ITEM_REF" --reason "completed"
```
Surface any release failure; never swallow it.

### 11. Final Output

After advancement and release, report fields/count/purpose, actual served
transition and freshly resolved next skill. For Blitz include the verified
execution-document slug and fresh handoff.

## 12. Completion

All nonempty applicable artifacts evaluated, findings addressed in permitted
fields, every write read back, target reached, claim released and report shown.
Blitz additionally needs exactly one linked/readback execution document.
DB read failure stops; an operator question is a checkpoint—answer before
continuing. Failed work cannot advance.
