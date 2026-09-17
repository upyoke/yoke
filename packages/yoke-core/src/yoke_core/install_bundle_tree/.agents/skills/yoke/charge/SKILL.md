---
name: charge
description: "Direct-mode entrypoint — compute the frontier, present the ranked table, confirm with operator, and dispatch to the correct downstream adapter."
argument-hint: "[--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]"
---

# /yoke charge

Direct-mode entrypoint for the charge flow. Computes the claim-aware schedule
via `yoke charge schedule`, presents a formatted table of ranked items with
their adapter classifications, confirms the top pick with the operator, and
dispatches to the correct downstream skill (refine, shepherd, conduct, advance,
dash, blitz, polish, or usher). The `next_step` field is the dispatch truth: the pinned
workflow's registered skill binding produced it. The `adapter` column
remains in the table display for ranking diagnostics.

`yoke charge schedule` is claim-aware: each ranked step carries a `claim_state` (`unclaimed`, `claimed_by_self`, `claimed_by_other_live`, `claimed_by_stale`). Steps with `claim_state='claimed_by_other_live'` stay on the ranked frontier for diagnostics but must NOT appear in the operator-facing Runnable table or be selected for dispatch — that is the assignability rule defined in `yoke_core.domain.scheduler_types.is_assignable_claim_state`.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--dry-run` — Show the frontier table and stop. Do not confirm or dispatch.
- `--item PREFIX-N` — Target a specific item instead of the highest-ranked one.
- `--project P` — Explicit project scope; bypasses the workspace-home filter.
- `--wip-cap N` — WIP cap override (default: 5).

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent. Charge is a routing handoff: present the frontier and dispatch rationale clearly enough that the chosen downstream skill can begin without re-litigating why it was selected. Do not dump the whole schedule.

**Think, don't just rank.** The frontier table is a decision aid, not a substitute for judgment. Surface blockers, adapter fit, and hidden readiness gaps instead of blindly following the top score.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1–3. Schedule and frontier | `/yoke charge` was just invoked | [`frontier.md`](frontier.md) |
| 4–6. Select, confirm, dispatch | The frontier table is presented and not `--dry-run` | [`select-and-dispatch.md`](select-and-dispatch.md) |
| — Event shapes | You need what this command emits | [`events.md`](events.md) |

## Start

Read [`frontier.md`](frontier.md) and follow it.
