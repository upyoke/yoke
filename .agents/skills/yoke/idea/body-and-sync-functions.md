# Idea — Typed Operation Depth

Use registered `yoke` adapters; they build the same typed function envelope.
The [function index](../../../../.yoke/docs/reference/db-reference/functions.md)
routes each registered id to its sole family owner. Read that family and
the operation's --help before a write; this receiver does not duplicate schemas.

Envelope fields are function/version, authenticated actor identity, typed target,
payload and optional preconditions/options. Response success/result/error,
warnings/recovery_hint and event_ids are evidence, not permission to repeat a
mutation. Ambient session authority cannot be copied from another holder.
Malformed/unknown functions and claims failures retain their named refusals.

## Use the existing operation for the question

| Need | Registered function family |
|---|---|
| Full intended field; heading addition; targeted section | items.structured_field.replace / append_addendum / section_upsert / section_append |
| Chronological execution checkpoint | items.progress_log.append |
| Named item-section read/write/delete | items.section.* |
| One scalar field | items.scalar.update |
| Pinned stage/gates | lifecycle.transition.execute |
| Persisted task body/metadata/decomposition/progress | workflow_item.epic_task.* / workflow_item.epic_progress_note.append |
| Unified DB profile and attestation | db_claim.amend |
| Exact/planned/tentative/exemption path coverage and amendments | claims.path.* |
| Item ownership and holder reads | claims.work.* |
| Explicit requested generated-board refresh | board.rebuild.run |
| Native agent or packet rendering/checks | agents.render.* / packets.* |
| Method-backed requirement and evidence | qa.* |
| Narrow item/events/project capability reads | items.get.run / events.query.run / projects.capability.has |

Field-targeted section_upsert accepts field plus heading_level and preserves
surrounding field content; omission targets item_sections with ordering.
Section-append's actual schema differs: use its registered help rather than
inventing a field flag. Progress Log always uses its dedicated timestamping append.

Path amendment supports adding or removing named paths; removal needs integration
target and retained committed coverage. It is not merely a widen alias.
Typed acquire resolves the public item; release targets its actual claim_id.
Task targets include public_ref/task_num. Item ids are bare resolved global ids,
never public sequence tails.

## DB payload and permanent history

Unified db_claim.amend atomically updates profile/compatibility attestation;
apply `mutation_intent="apply"` requires migration_strategy and modules.
In pre_merge_readers_writers, `role` is only `reader` or `writer`;
schema modules are writers. Reviewed-none meta discussion is an explicit
workflow-stamped negative, not a mutation deferral.

For apply with modules, append an AC naming every declared module:
`- [ ] AC-N: Each declared migration entry remains permanent ordered history,
safe to re-run and never deleted after apply; boot convergence records
filename-stem membership in the authoritative ledger.`

Use supported field-targeted section_upsert or guarded additive transform,
not a fictitious field-bearing section-append command. A contrary delete-after-
apply AC must be explicitly corrected under governed instructions; do not keep
both contradictory requirements. No item applies migrations to an authoritative
DB or removes ordered history.
