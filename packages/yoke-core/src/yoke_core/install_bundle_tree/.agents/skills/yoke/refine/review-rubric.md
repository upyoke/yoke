# Refine — Review Rubric

## 5. Mandatory first inventories

Before any other critique, list every approved structural decision under
**Decisions to preserve**: trees, file layouts, naming, exact stays/moves,
interfaces and concrete ACs. The supplied tree is canonical.
List user-voiced questions, observations, screenshot/evidence links and direct
quotes under **User questions and evidence to preserve**; retain them verbatim.

Carry all survey drift/overlap/shipped findings into critique. Use item events
or bounded recent telemetry to ground systemic context failures. Verify every
named path/function/script/key/column against live source; use semantic
anchors alongside drifting line numbers.

## Required lenses and gates

- **End-to-end:** trace trigger through UI/CLI/workflow to outcome, defaults,
  errors and help/docs. Add obvious missing requirements without redesigning.
- **Blast radius:** actual search of callers, imports, tests and environments,
  configs/scripts/docs and downstream consumers; include zero-residue ACs
  for removal/rename instead of remembered file lists.
- **Cleanup/recovery:** identify obsolete code, tests, config, docs and shims and
  partial-state/failure/rollback recovery. Retain permanent migration modules.
- **Open questions:** resolve or explicitly default decisions affecting
  interfaces, files, model or user behavior before item-artifact handoff.
  Mere task ordering can be deferred; firm FRs cannot depend on unknown answers.
- **Codebase-reader naming:** every proposed live path/symbol/test/doc/command/
  event/setting/heading/comment explains current function to a reader without
  its planning artifact. Reject work-item/strategy/plan/phase/task/AC/branch/
  batch provenance unless it is runtime/domain vocabulary.
- **Guard-permitted verification:** prescribe registered `yoke` adapters,
  watchers or source-dev wrappers. Direct inline imports of product runtime
  are refused as BLOCKED_AGENT_COMMAND_SHAPE; fix the actual command.
- **Reuse:** name existing helpers/templates/skills/modules/events/commands.
  Empty reuse requires **no relevant existing surface**, with searched scope
  and rationale before proposing new infrastructure.
- **Quality:** smallest complete AC shape and explicit out-of-scope boundaries
  when creep is invited; remove parameter sprawl/copy variation/leaky wrappers.
- **Efficiency:** justify each new table/event/skill/config/command/prompt by
  extension-versus-creation evidence. No speculative intermediate work.
- **Future concept:** name the honest v0 primitive, concrete consumers and
  future non-goals, or deletion/absorption target; consume existing claims,
  actors, events, phase runs, journals and packets before inventing duplicates.
- **Readability:** measure prompt/doc/script sizes; flag truncation pressure.

## File Budget, when enabled

Treat it as a first-class dimension. **Item-artifact refinement** covers the
item's actual implementation scope; **Generated-task-plan refinement** covers
each persisted task's scope under required_per_task policy.

Use only the central effective projection. Universal350 authored lines is hard,
<=300 is the design target; owner is `yoke_core.domain.file_line_check`.
Do not manufacture a budget when the axis is off.

For implementation-bearing item artifacts, add a missing File Budget with
likely exact files and single responsibilities. Investigate unknown shape or
escalate; do not advance unresolved. Under required_per_task, each task creating
or growing code needs its own concrete budget; no oversized responsibility
hidden in a worktree plan. Explicitly name touched300+ files and their split
plan. Counts, "all callers" and approximations are not path enumeration.

## DB claim consistency

Governed schema/migration/backfill/bulk/audit prose needs a declared matching
profile/attestation or an explicit reviewed-none amendment. Read
db_mutation_profile and dispatch `db_claim.amend` before handoff.
The unified payload atomically updates profile plus compatibility attestation.

For meta governance discussion that mutates nothing, amend state:none with
the reason; this stamps reviewed-none evidence. Never scrub DDL vocabulary or
backtick it to evade GATE_DB_CLAIM_PROSE_MISMATCH. Source facts, not keywords,
determine the honest claim.

An apply-intent profile with migration_modules must specify permanent ordered
`NNNN_slug.py` entries, safe to rerun and applied by boot convergence. Never
require deleting a module, waiting until every installation has applied it,
or applying to an authoritative DB from the item.

## Artifact dimensions

**Spec/body:** clear problem/purpose, scope/non-goals, all user-journey steps,
errors/validation/messages/edge cases, partial-write recovery, actual discovery,
complete cleanup, evidence-backed migration and current docs. Verified code
anchors; canonical testable `- [ ] AC-N: ...`; include meaningful wiring,
cleanup/residue/error ACs. Name upstream/downstream dependencies and implementation,
test, documentation and configuration files. Self-consistency across narrative,
FRs, ACs/non-goals and resolved questions: propagate resolutions everywhere.

Sizing: 5+ FRs across3+ subsystem files probably needs decomposition;
7+ FRs or10+ ACs should be flagged for task decomposition, not auto-created.

**Design:** full interaction sequence including empty/error/boundary states;
remove replaced components/routes/help/screenshots and complete the journey.

**Technical/worktree plan:** session-sized reviewable tasks, never empty.
One/two closely related files under~50 changed lines usually stay one task.
Interfaces give exact parameter/type signatures, model field names/types
and concrete output examples. Verify source references, risks/mitigations,
persisted task and lane alignment, concurrent modification/merge order,
cleanup coverage, migration evidence and direct efficient implementation.
Name functional surfaces that remain clear without task/spec provenance.

**QA:** name observable Browser/command/machine behavior. Prefer covering project
plans; otherwise explicit method-backed instructions, expected result and
method config. Browser routes/waits/assertions/captures belong to browser-check
or browser-inspection configuration, not a new posture field. Follow
[Where a Browser case runs](../../../../.yoke/docs/reference/browser-scenarios.md#where-a-browser-case-runs);
a change no server serves selects approval_on_done.

**Caveats:** close all material item-level questions or defaults; task-order
deferrals may remain. Link deferred work with public refs and challenge anything
whose deferral leaves the current outcome incomplete.

**Blitz:** exactly one unarchived same-project execution document must
cold-start outcomes, slices, areas, coordination, verification/delivery,
unresolved decisions and parent/no-parent relationship. Missing/ambiguous/
conflicting/incomplete documents block at the active stage before linking.

## Critique output and command source

Include both inventories, **Strengths**, **Issues Found** and concrete
**Recommended Changes** naming what/where. Do not write before the preservation
and escalation checks in update-protocol.

Pre-merge Yoke source checks use `yoke dev run -- <command>`; post-deploy
Command tests use `yoke watch pytest -- <paths>` directly with candidate cwd.
Candidate-bound bare python/yoke imports must record candidate origins;
missing/outside origins are a named refusal, never a pass. Lane, external
project and endpoint-only allow-tree-mismatch cases retain product imports.
