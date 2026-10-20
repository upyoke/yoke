---
name: conduct
description: "Execute the pinned workflow segment bound to conduct through generated task lanes, the Engineer/Tester loop, and integration simulation."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "PREFIX-N [--max-attempts N] [--no-chain]"
---

# /yoke conduct PREFIX-N

Run the pinned Conduct segment through generated task lanes, Engineer/Tester
validation and integration simulation in the same harness session; no manual relaunch.
A launch-assigned item
takes its work claim first; never manually register the session. Obey fetched
Workflow Execution Instructions and every AC.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

```text
yoke sessions touch --mode conduct
```

## Phase map — read before acting

Do NOT read all files upfront. Load the current phase and its named supplements.
The ordered pin, effective policies and half-open binding own routing, lanes,
gates and the fresh through-stage handoff; never route by workflow name.

| Phase | Owner |
|---|---|
| Entry contract | [entry-gates.md](entry-gates.md) |
| Claim, survey, activation | [entry-activation.md](entry-activation.md) |
| Engineer/Tester loop | [engineer-tester-loop.md](engineer-tester-loop.md) |
| All tasks reviewed; integration simulation | [simulation-gate.md](simulation-gate.md) |
| Every exit | [cleanup-report.md](cleanup-report.md) |
| Unparseable output | [retry-budgets.md](retry-budgets.md) |

Use [file-map.md](file-map.md) for supplemental owners.

## Autonomous, thin orchestration

Every subagent return immediately continues its next phase. Emit a concise
checkpoint, then act; no unrequested pause or handoff menu. Activation creates
registered lanes and continues here, without relaunch or parent-session stop.

Read item/task specs, registered state and verdicts; dispatch Engineer, Tester,
Simulator, and Architect only through the named auto-fix path. Do not investigate
implementation source, edit code/tests/docs or run builds/tests directly.
Implementation belongs to Engineer; Tester and Simulator are read-only. The
exhausted-Tester fallback in [dispatch-context-verify.md](dispatch-context-verify.md)
is the sole direct verification exception. Never simulate integration yourself.

Each cold dispatch needs exact item/task identity, absolute registered paths,
specs, current diff captures, QA and test commands. Naming describes current
function/mechanics/domain, never planning provenance. Apply the Simplify lenses in
`code-and-cli.md`: reuse, quality, efficiency and future concepts. Failures are systemic evidence:
query yoke events tail --limit 20, file a field-note before retry and name the
missing contract or recovery, never blame an agent.

Never auto-waive blocking QA. Missing Browser target/infrastructure halts for
operator repair or explicit waiver through its authorized surface. Nonblocking
waivers follow QA help; no invented force/bypass. Progress across tasks belongs
in the parent's Progress Log; per-task notes remain epic_progress_notes.

A level_change handoff precedes release wait. Follow the
[Stage-level routing rule](../../../../.yoke/docs/agents/levels.md);
workers may launch their own successor. Refresh the bound skill and claim at
the through-stage boundary; Conduct never owns landing or terminal delivery.
