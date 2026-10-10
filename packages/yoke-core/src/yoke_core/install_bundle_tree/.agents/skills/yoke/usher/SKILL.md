---
name: usher
description: "Unified merge+deploy command. Takes items from implemented through merge, deployment, and done-transition. Inline orchestration skill -- no subagent spawned."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]"
---

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

# /yoke usher PREFIX-N [PREFIX-N ...]

Inline orchestration: no subagent. Carry explicitly named implemented items
through governed merge, deployment and actual done-transition. Read the item's
Workflow Execution Instructions and immutable live binding; no remembered
workflow progression or forced stage. A current worker mandate can reserve
deployment batching to its orchestrator.

| Flag | Effect |
|---|---|
| --dry-run | Read-only plan; stop before execution. |
| --merge-only | Land only, record delivery wait and retained claim. |
| --deploy-only | Deliver already-landed items; no repeat landing. |
| --resume PREFIX-N | Single-item deploy-only at authoritative run stage. |

At least one complete public ref or resume target is required. Explicit items
already authorize execution; no extra confirmation.

```text
yoke sessions touch --mode usher
```

| Phase | Read before acting |
|---|---|
| Collect: admission, scoped dependency gate, ordering, dirty state, claims | [collect.md](collect.md) |
| Dry-run/plan | [plan.md](plan.md) |
| Land through governed engine and recover exact exit | [merge.md](merge.md) |
| Route no-delivery or selected-flow run | [deploy.md](deploy.md) |
| Honest state/report/recovery and releases | [finalize.md](finalize.md) |

Read phases in order; deploy-only skips merge, merge-only stops at delivery
wait. Generated-task merging is an internal procedure reached from merge's
effective child/lane policy, not another skill or parent-only landing.

Every merge/deploy failure preserves receipts, run stage and a named recovery.
The batch halts on unresolved failure. Run status/current_stage plus item
membership own release evidence; events are diagnostic telemetry.
Queue projects use their declared queue, with combined-head merge_group proof,
never local fallback. Phase exit handling distinguishes coordination, landed
cleanup, user files and true failure; cancelled checks are no verdict.

Usher owns implemented-to-done and manual delivery. Route A's done-transition
skip-deploy is only verified no delivery; Route B closes through yoke merge item
with selected-flow run evidence. Absorb exit7 into routing, never force done.
Only verified terminal success reports completion.

Before a nonterminal stop, checkpoint current stage, committed/dirty work and
next command. A handoff reason=level_change takes precedence over release wait;
follow [stage-level routing](../../../../.yoke/docs/reference/session-level-routing.md)
and its exact successor command. Release waits obey current claim/park mandate.
