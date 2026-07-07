---
title: context_routing cutover — exception-pathway justification
date: 2026-04-28
exception: record_audit_fingerprint
module: context_routing_cutover
---

# context_routing cutover — exception-pathway justification

This record is the paired justification required by the governed
DB-mutation rule in `CLAUDE.md` (*"every exception path is named"*). It
explains why the `context_routing_cutover` one-shot migration was routed
through `record_audit_fingerprint` instead of the declared
`governed_migration_module` runner.

## What changed

The coarse project-level columns `projects.context_always`,
`projects.context_by_topic`, and `projects.notes` were removed from the
`projects` table. Project-wide always-included docs and topic-keyed doc
sets now live in the `context_routing` Project Structure family
(keyed-set, project-attached). The reserved `entry_key="always"` holds
the project-wide set; any other `entry_key` is a topic name.
`projects.notes` was discarded — see
`docs/archive/decisions/projects_notes_decision.md` for the rationale.

This is the final Phase 0 cutover-proof slice. With it landed, the
`projects` table retains only identity/repo metadata
(`id`, `name`, `emoji`, `repo_path`, `default_branch`, `github_repo`,
`created_at`); every cross-cutting per-project setting is now governed by
Project Structure or the per-project capability registry.

## Why the governed runner could not apply this

The compatibility class of the mutation is `pre_merge_breaking`:

* The `projects` table is on every live reader path (doctor, board, item
  rendering, project lookups). Removing columns would break any
  concurrent reader or writer that still reads the old schema mid-rollout.
* The governed `governed_migration_module` runner refuses
  `pre_merge_breaking` mutations by contract. This is the governance
  theorem: the runner accepts only mutations attested as `pre_merge_safe`
  with the four authored compatibility fields populated.

## Why expand-contract was rejected

The usual decomposition for a `pre_merge_breaking` cutover is
expand-contract — ship the new family, dual-read from both sources for a
window, then ship the contract that drops the old columns. Yoke's
constitutional rule (Gen 2 §1.5 #4) bans dual-read windows. Every reader
must resolve to one source of truth at a time. That makes expand-contract
structurally unavailable here.

A release-phase governed apply path that tolerates `pre_merge_breaking`
mutations inside a short maintenance window is on the roadmap but does
not exist yet. Waiting for it would block the closure of the Generation 2
Phase 0 plan that specifically cuts over the remaining coarse `projects`
columns into Project Structure. The deploy_defaults cutover precedent
(`docs/archive/decisions/deploy_defaults_cutover.md`) used the same
exception pathway for the same reason.

## Why the cutover window is acceptable today

Yoke is currently in founder-build posture: a single operator, one
active installation, no concurrent production traffic against the live
`yoke.db`. The code change and the schema change ship in the same
commit range, so no deployed reader ever sees one without the other. The
one-shot runs locally during implementation (against `YOKE_DB`) and
again on the operator's primary install at merge time. There is no
window in which a live reader sees an intermediate state.

## What replaces the exception in the future

Two durable replacements are planned:

1. A **release-phase governed apply** path that accepts
   `pre_merge_breaking` mutations inside an explicit maintenance window
   (reader pause + apply + resume). When that lands, future cutovers like
   this one go through the governed runner and the exception pathway is
   not needed.
2. A general **maintenance-mode** substrate for the Yoke control plane
   that pauses writers, applies destructive schema changes, and releases
   — so `pre_merge_breaking` mutations have a first-class home.

Either replacement supersedes the exception-pathway justification recorded
here. If a future cutover of similar shape reuses this rationale unchanged,
the author should instead wait on one of the two replacements above rather
than cite this record.

## Audit evidence

The applied cutover emits a `migration_audit` row:

* `migration_name = "context_routing_cutover"`
* `state = "completed"`
* `exception_reason` points at this file path.

The `HC-oneshot-migration-coverage` doctor check pairs the call site
against this record. The
`check_implementing_to_reviewing_implementation_gate` gate finds the audit
row keyed on `migration_name` and counts it as the apply-evidence the
ticket profile's `migration_modules` list names.

Once the audit row lands on the authoritative DB
(`data/yoke.db`), the cutover module itself is deleted from the live
tree per the "delete completed migrations" rule in `CLAUDE.md`. Git
history preserves the module body; this decision record preserves the
reasoning.
