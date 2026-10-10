---
name: refine
description: "Read item artifacts, critique them, and write improved work item artifacts back through sanctioned Yoke update surfaces."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N}"
---

# /yoke refine {PREFIX-N}

Critique and enhance stored item artifacts through sanctioned structured writes.
Require a complete public ref. Standalone and routed invocations both advance
on success through the item's exact pinned refine segment.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Boundaries from the first action

No worktree, implementation-code edits or commits. Hold the item work claim
before artifact, File Budget, path-claim or GitHub-body writes. Identity is not
authority. The binding is three rungs: source, one active stage, handoff;
failure/interruption cannot advance beyond the actual live stage.

**Cardinal rule: never subtract, only add.** Preserve every existing decision,
AC, question, observation and evidence. Add missing sections, ACs, verification,
discovery, scope and links. Grammar/clarity edits in place may not change meaning.
Never delete, replace substance, paraphrase user voice, or abstract concrete
decisions. Every rewrite is lossy: enhance rather than rewrite.

**Escalate, don't correct:** major verified errors—wrong references,
contradictions, flawed approach or scope conflict—stop writes and advancement.
Surface them to the operator; remain at REFINE_ACTIVE_STATUS until resolved.

Refine does not derive QA requirements from workflow selection or Browser
posture. Existing default/attached plans materialize at their declared
transitions. Add `qa.requirement.add` only for explicit verification outside them.

When `ITEM_NEXT_SKILL=blitz`, leave exactly one verified project execution
strategy document linked through `strategy.execution.link`. This is metadata;
Blitz activation owns atomic document-claim acquisition.

## Phase map

| Phase | Read before acting |
|---|---|
| 1. Exact pin and supported binding | [workflow-context.md](workflow-context.md) |
| 1b–2. Claim, readiness, enter, gather | [entry-and-gather.md](entry-and-gather.md) |
| 3–4b. Survey, focus and independent policy axes | [survey-and-focus.md](survey-and-focus.md) |
| 5. Critique | [doctrine.md](doctrine.md), [review-rubric.md](review-rubric.md) |
| 6–12. Add, verify, transition, release, report | [update-protocol.md](update-protocol.md) |
| Before advancement: final path closure | [closure.md](closure.md) |
| Readiness repair branches | [`readiness-repair.md`](readiness-repair.md) |
| Blitz after verified writes, before advancement | [blitz-execution-document.md](blitz-execution-document.md) |

Start with workflow-context. A `handoff` with `reason=level_change` takes
precedence over release wait; follow
`.yoke/docs/reference/session-level-routing.md`. Workers may launch a successor.
