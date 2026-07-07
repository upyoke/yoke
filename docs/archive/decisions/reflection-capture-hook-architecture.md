# Reflection-capture moves from skill-prose recipe to PostToolUse Agent-tool hook

## Status

Accepted. Landed in YOK-1832 (claim 287).

## Context

Every Yoke subagent role (engineer, tester, simulator, architect, boss,
product manager, product designer) is taught to emit a delimited reflection
block in its final response. The block format is shared
(`runtime/agents/_shared/ouroboros-reflection-contract.md`); the agent-side
contract is "include zero or more entries inside
`---REFLECTION-START---` / `---REFLECTION-END---` wrappers and the
substrate will persist them."

Before this slice the persistence step was a **prose contract**: an
operator-authored Bash recipe at step 5m of
`.agents/skills/yoke/conduct/dispatch-context-artifacts.md`. The recipe
saved the subagent's full output to a temp file, looked up the in-flight
item's project, and invoked
`python3 -m runtime.api.domain.reflection_capture --output-text ...`
after every Agent-tool return.

The recipe worked when the operator (or the orchestrator) ran it. In
practice, every `/yoke conduct`, `/yoke shepherd`, and
`/yoke simulate` invocation that did not hand-run step 5m silently
discarded every reflection that subagent emitted. The 2026-05-22
discovery walker confirmed the gap at scale: across ~7,200 local
transcripts, ~5,000 reflection blocks were observable in the agent
output (recoverable from transcript JSONL) but never reached
`ouroboros_entries`.

The truncated `tool_response_preview` field on
`HarnessToolCallCompleted` (capped at 512 chars) was the only persistent
trace for short reflections, and useless for any block longer than that.

## Decision

Replace the skill-prose recipe with a `PostToolUse` hook that fires for
every `Agent` tool call, reads the **full** `tool_response` (no
4096-char truncation that
`observe_parsing._extract_response_text` would impose), and dispatches
through the same `capture_reflections` pipeline the operator-debug CLI
already exercises.

The hook lives in `runtime/api/domain/reflection_capture_hook.py` and is
wired into the universal `PostToolUse` `Agent` matcher through
`runtime/api/domain/harness_hook_ordering.py`. The Claude
`settings.json` adapter renders the matching block automatically via the
existing `agents_render` pipeline.

The hook always returns `AUDIT_ONLY` — reflection capture is
non-blocking by contract. Any parse / persistence failure is recorded on
the `ReflectionCaptureHookFired` event and the corresponding
`ouroboros_entries` rows are skipped without aborting the tool call.

When the multi-shape parser observes a reflection-bounded block whose
shape no shape parser recognises, the hook additionally emits
`ReflectionCaptureHookUnhandled` with the raw block excerpt and the
classification it attempted. The new doctor HC
`HC-reflection-capture-unhandled` surfaces those events as WARN in
`/yoke doctor` so operators can extend the parser (or confirm the
shape is a one-off and add it to the explicit false-positive registry).

## Codex parity — Approach A (Codex-conditional skill-prose recipe)

Codex subagents are launched via the generated `.codex/agents/yoke-*.toml`
custom-agent adapter path, not as in-process `Agent` tool calls.
`PostToolUse` on the Codex side will never fire for an `Agent` matcher;
the Codex hook renderer intentionally emits hooks only for `Bash` and
`apply_patch|Write|Edit`.

Three candidate implementations were considered for AC-14 / AC-28:

1. **Approach A (chosen)** — Codex-conditional skill-prose recipe in
   `.agents/skills/yoke/conduct/dispatch-context-artifacts.md` that
   runs `capture_reflections` after each subagent response when
   `$YOKE_EXECUTOR=codex`. Smallest diff; preserves AC-5's purge for
   Claude (the dominant operator surface) and adds the Codex-only
   escape hatch via the same operator/debug CLI the hook itself uses
   internally. No new Codex hook module, no `agents_render_codex.py`
   change, no custom-agent TOML schema dependency.
2. **Approach B** — Codex-side hook on subagent-dispatch-shaped Bash
   calls. Inspect the Bash `command` field for `codex agent:
   .codex/agents/yoke-*` in a new sibling hook module and emit on
   match. Rejected: ~120 LOC + a new doctor HC for the Codex-side
   matcher, against ~0.7% (4 / 591 archived sessions) actual
   completed-reflection emissions in the historical Codex corpus.
3. **Approach C** — Custom-agent layer post-processing via
   `agents_render_codex.py`'s `post_response` directive. Rejected:
   would require a Codex TOML schema feature that isn't documented as
   supported; not a clean fit for the small ROI.

**What the skill recipe does:** when `$YOKE_EXECUTOR=codex`, the
conduct flow writes the captured subagent response to a `/tmp` temp
file, resolves the in-flight item's project, and calls
`python3 -m runtime.api.domain.reflection_capture --output-text <tmp>
--default-agent <role> --project <project>`. The CLI is the same
operator/debug surface the AC-7 contract retains; it runs the same
multi-shape parser + persist pipeline the Claude PostToolUse hook
invokes. Skill-body action is required only for Codex; Claude sessions
remain hook-driven with zero skill-body work (the AC-5 purge stands
for the dominant operator surface).

**Out of scope under this approach:** Codex sessions do not emit the
`ReflectionCaptureHookFired` / `ReflectionCaptureHookUnhandled` events
the Claude hook emits — those events drive Claude's `/yoke doctor`
HC-reflection-capture-hook-coverage gate. The Codex equivalent
audit-trail is the existing `events list --event-name OuroborosEntryInserted`
plus the `ReflectionCaptureUnhandled`-equivalent failure modes the CLI
already records via `--errors` reporting; a richer Codex-side telemetry
gate is a future-concept follow-up (filed under a separate ticket only
if observed misses warrant it).

**Operator note on cross-harness corpus scope:** the 2026-05-22
YOK-1832 cross-harness investigation walked
`~/.codex/sessions/` (26 active) +
`~/.codex/archived_sessions/` (591 archived). After extending the
`transcript_reflection_audit` walker to recognise Codex's
`{timestamp, type, payload}` envelope (including
`function_call_output.payload.output`), the audit found 4 parsed
reflection blocks across the full archived corpus — vs the 5,003
entries the Claude-corpus backfill recovered. This evidence-bound the
Approach choice toward A; the operator-escalated framing of
"non-negotiable cross-harness backfill" was based on the prior
assumption that Codex emissions were comparable in volume to
Claude's, which the archived data does not support.

## What changed

* New module `runtime/api/domain/reflection_capture_hook.py` —
  `evaluate(HookContext) -> HookDecision` always returns AUDIT_ONLY,
  reads the full `tool_response`, maps `subagent_type`
  (`yoke-engineer` → `engineer`, etc.) to the canonical role,
  resolves the in-flight item's project, calls
  `capture_reflections`, emits the two new events.
* Multi-shape parser refactor across three sibling modules
  (`reflection_capture_shapes.py`,
  `reflection_capture_shape_parsers.py`,
  `reflection_capture_freeform.py`) returning the structured
  `CaptureResult` AC-16 requires.
* `runtime/api/domain/harness_hook_ordering.py` —
  `_POST_AGENT` chain (`reflection_capture_hook -> observe`) under the
  `PostToolUse` `Agent` matcher.
* `runtime/api/domain/populate_registry_data_authoritative.py` —
  `ReflectionCaptureHookFired` (INFO) +
  `ReflectionCaptureHookUnhandled` (WARN) registered; four retired
  tombstone entries compacted onto two lines to honor the 350-line cap.
* `runtime/api/engines/doctor_hc_reflection_capture_hook_coverage.py` —
  new HC + registration via `doctor_registry_harness.py`.
* `runtime/api/tools/transcript_reflection_audit.py` — sanctioned
  transcript audit tool that re-walks local Claude Code transcripts and
  confirms `blocks_unrecognized == 0`.
* `.agents/skills/yoke/conduct/dispatch-context-artifacts.md`,
  `docs/OVERVIEW.md`, `docs/agents.md`,
  `runtime/agents/_shared/ouroboros-reflection-contract.md`, plus the
  six canonical agent bodies + the two sub-`reflection.md` files —
  legacy "parent dispatch session captures" / "Conduct's concrete
  capture path uses python3 -m runtime.api.domain.reflection_capture"
  language replaced with the hook-captured semantics.
* Generated Claude / Codex agent adapters regenerated via
  `agents.render.run`.

## What kept working

* `python3 -m runtime.api.domain.reflection_capture` CLI retained as
  the operator/debug adapter for ad-hoc backfills against captured
  transcript text. Module docstring updated to reflect operator/debug
  status — not primary capture path.
* Existing `reflection_capture_recipe_event` recipe-event marker
  dispatch still fires for every captured entry; the hook flow consumes
  the same `capture_reflections` pipeline that already chains it.

## Where the old surface lives now

* The original 28-line step-5m recipe is deleted from
  `dispatch-context-artifacts.md`. Git history (commit on the YOK-1832
  branch) preserves it.
* The CLI itself stays in place at
  `runtime/api/domain/reflection_capture.py` as an operator/debug
  adapter.
* The historical backfill artifacts under
  `projects/yoke/qa-artifacts/1832/` remain gitignored — they were
  the input fixture set for the production parser and the source of
  truth the transcript audit tool benchmarks against.

## Follow-up

* **AC-21 long-tail parser extension** is the remaining open work. The
  7 documented Claude shape variants (Shape E + bold-field,
  markdown-header reflections, `(no entries)` literal, bare
  `---END ENTRY---`, Shape B + bold-field, `type:` field-led entries,
  bold-headed markdown freeform) need parser entries before
  `blocks_unrecognized` reaches zero on the Claude corpus. Codex
  unrecognized-block patterns (regex source, grep output, prose
  mentions) need parallel false-positive classifiers.
* **Codex telemetry symmetry** is a future-concept follow-up: a
  Codex-side gate equivalent to `HC-reflection-capture-hook-coverage`
  is only worth building if observed Codex misses warrant it. Today's
  4-entries-across-591-archived-sessions volume does not.
