---
name: refine
description: "Read item artifacts, critique them, and write improved work item artifacts back through sanctioned Yoke update surfaces."
argument-hint: "{PREFIX-N}"
---

# /yoke refine {PREFIX-N}

Standalone capability for refining backlog item artifacts. Reads the item's structured fields, critiques them for completeness, clarity, and testability, and writes improved content back through sanctioned Yoke update surfaces.

This is an explicit, operator-invoked capability that Codex can execute directly. It does not require `/yoke do`, lane-aware routing, or lifecycle-family ownership wiring. `{PREFIX-N}` accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1. Resolve the pin | The argument just arrived | [`workflow-context.md`](workflow-context.md) |
| 1b–2. Claim, enter, gather | The pin resolved and the skill guard passed | [`entry-and-gather.md`](entry-and-gather.md) |
| 3–4b. Survey, focus, re-check | The artifacts are read | [`survey-and-focus.md`](survey-and-focus.md) |
| 5. Critique | The focus and the enabled axes are settled | [`doctrine.md`](doctrine.md), then [`review-rubric.md`](review-rubric.md) |
| 6–12. Apply, verify, advance, release | The critique is emitted | [`update-protocol.md`](update-protocol.md) |
| Final. Path closure | Updates are written, before the status advance | [`closure.md`](closure.md) |
| — Readiness gate repair | A readiness or path-claim gate returned anything but `pass` | [`readiness-repair.md`](readiness-repair.md) |
| — Blitz execution document | `ITEM_NEXT_SKILL=blitz`, after step 7 and before step 9 | [`blitz-execution-document.md`](blitz-execution-document.md) |

## Modes and lifecycle

Refine always advances status on successful completion, whether invoked directly (e.g., `/yoke refine PREFIX-N`) or via scheduler routing.

Resolve the active `refine` segment from the item's immutable workflow pin. Interpret `skill_bindings` against the ordered `stages` with the runtime's half-open interval (`from_stage_id <= current < through_stage_id`). This skill supports the refine skill's three-rung contract: binding source → one in-progress stage → binding handoff. Use those served stage ids for entry, re-entry, and completion; never select a branch from a literal workflow id.

If refine fails or is interrupted, the item must not advance past its current
served stage.

## Constraints — these bind at every phase

- No worktree required.
- No code edits or commits.
- A Blitz must leave Refine with exactly one verified execution strategy
  document linked through `strategy.execution.link`. Refine links metadata
  only; `/yoke blitz` owns atomic document-claim acquisition and execution.
- Artifact writes are work writes: work item/spec/body sections, File Budget, path-claim register/widen/narrow/release, and GitHub issue-body edits are shared coordination state; hold the item claim before mutating them, and treat `who-claims` session ids as identifiers, not authority.
- Full-field rewrites go through the `items.structured_field.replace` function call; additive transforms (preserve existing content, append a `## heading`-led block) go through `items.structured_field.append_addendum` / `items.structured_field.section_upsert` / `items.structured_field.section_append`; see [`update-protocol.md`](update-protocol.md) step 6 for the full surface contract and [`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md) for the envelope shape.
- Both standalone and routed modes advance status on successful completion.
- Refine does not derive QA requirements from an item's selected workflow or Browser posture. Project-default and item-attached plans materialize at their declared lifecycle transitions. Add an explicit item-specific requirement through `qa.requirement.add` only when the refined verification contract calls for coverage outside those attached plans.

## Cardinal rule: never subtract, only add

Refine enhances artifacts by adding what's missing — it never removes, replaces, or paraphrases existing content. The operator's words, questions, evidence, decisions, and ACs are input constraints, not rough drafts to be polished. You may add sections, add ACs, add verification commands, add blast-radius analysis, add scope boundaries, and add cross-references. You may improve wording **in place** (grammar, clarity) without changing meaning. You may NOT delete content, abstract specifics into generalities, paraphrase user questions into scope language, or replace concrete statements with vague ones.

Every rewrite is a lossy transformation. Refine does not rewrite — it enhances in place and appends.

## Escalate, don't correct

If the spec contains a major error — wrong file references, contradictory requirements, a fundamentally flawed approach, scope that conflicts with existing work — do NOT silently fix it. **Stop and surface the issue to the operator.** The operator may have context you don't. Refine is not authorized to make judgment calls about what the operator "really meant" when the spec contradicts reality. Do NOT advance status. Leave the item at `REFINE_ACTIVE_STATUS` and report what you found.

The corollaries that reinforce the cardinal rule, and the operating principles
the critique applies, are in [`doctrine.md`](doctrine.md) — read before step 5.

## Start

Read [`workflow-context.md`](workflow-context.md) and follow it.
