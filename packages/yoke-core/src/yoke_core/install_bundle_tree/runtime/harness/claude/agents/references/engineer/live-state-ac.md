# Engineer — Live-State AC Execution Semantics

Read when ACs name live DB, deployments, external services or shared mutable
state. Architect tags execution intent; untagged intent never grants mutation.

## `[READ-ONLY]`

Inspect/query/verify only. Satisfied condition records passing QA; mismatch
records failing QA with observed versus expected state, reports and stops.
Do not repair live state: the mismatch is the deliverable (e.g. missing CHECK
constraint is reported, never added under a verification tag).

## `[APPLY-MUTATION]`

Apply through that domain's sanctioned write path: governed schema history,
registered `yoke <subcommand>` control-plane updates (packet/--help), or declared
deployment pipeline for infrastructure. Read migration-protocol.md before DDL,
especially destructive work; author/rehearse, then boot convergence applies.
Verify resulting state. The intent label does not waive domain safeguards.

## Untagged live-state ACs

Default to `[READ-ONLY]`. Never mutate from ambiguous verification language.
Report ambiguity in structured output so parent requests Architect clarification.
