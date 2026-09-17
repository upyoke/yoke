# /yoke conduct — retry budgets and output-gate fallback chains

Read this when a Tester or Simulator dispatch returns no parseable
verdict, or when you need the retry constants. The loop and simulation
phase files name this file at the step that consumes it.

## Constants

```
MAX_TESTER_REPROMPTS=2
MAX_SIMULATOR_REPROMPTS=2
MAX_ARCHITECT_FIX_ITERATIONS=3
```

**Tester output gate fallback chain:** When the Tester returns no parseable verdict, `MAX_TESTER_REPROMPTS` controls the escalation chain:
- **Initial attempt:** Full prompt with diff (inlined if <=300 lines, externalized to temp file if >300 lines). See `engineer-tester-loop.md` step 7. If verdict found, done.
- **Retry 1** (`_tester_output_failures == 1`): Minimal prompt variant (no inline diff, file list only) with default model. See `dispatch-context.md` step 5i-minimal.
- **Retry 2** (`_tester_output_failures == 2`): Minimal prompt variant + `model: "opus"`.
- **After retry 2** (`_tester_output_failures > MAX_TESTER_REPROMPTS`): Conduct direct verification fallback -- run tests in the worktree directly. See `dispatch-context.md` step 5i-conduct-verify. This is a documented exception to the Thin Conduct Principle.

The constant controls when to escalate model (retry 2) and when to fall back to conduct verification (after all retries exhausted). It does not control when to give up entirely -- the conduct skill always produces a verdict.

**Simulator output gate:** When the Simulator returns no parseable result (neither `SIMULATION: CLEAN` / `SIMULATION: GAPS FOUND` nor fallback `CLEAN` / `GAPS FOUND`), the gate first classifies the failure mode, then selects a recovery strategy. `MAX_SIMULATOR_REPROMPTS` controls the retry budget via a three-tier retry chain:
- **Initial attempt (Tier 1):** Compressed two-phase integration simulation by default, unless `sim_force_standard_integration=true` overrides it back to the standard full-context prompt. If result found, done.
- **Classification:** If no result found, classify output as `context_exhaustion` (< 500 chars, mid-thought fragment, tool-call reasoning without report structure) or `formatting_omission` (structured report content present, but the two-line verdict block — `SIMULATION:` line and/or `EPIC: PREFIX-{N}` attestation line — is missing). Ambiguous cases default to `formatting_omission` (conservative).
- **Retry 1 (Tier 2) — formatting_omission** (`_simulator_output_failures == 1`): Re-invoke with escalated instructions demanding the full two-line verdict block as the first two lines of the response.
- **Retry 1 (Tier 2) — context_exhaustion** (`_simulator_output_failures == 1`): Re-invoke with compressed context + two-phase protocol + aggressive constraints (verdict-first, max 3 gaps, forbidden-operations list). See `simulation-gate.md` S6h for the full retry prompt.
- **Retry 2 (Tier 3) — ultra-compressed no-tool fallback** (`_simulator_output_failures == 2`): Re-invoke with ultra-compressed context (overlap matrix + dependency edges + one-line task summaries only — no interface contracts, no review summaries, no diff stats) and a hard no-tool mandate. The Simulator must produce its verdict from prompt content alone. This trades depth for guaranteed completion. See `simulation-gate.md` S6h for the full ultra-compressed prompt.
- **After retry 2** (`_simulator_output_failures > MAX_SIMULATOR_REPROMPTS`): HALT (safe default). Unlike the Tester gate, there is no conduct direct-verification fallback -- the conduct skill cannot simulate integration paths itself.
- **Ouroboros logging:** All gate exhaustion entries include the failure mode classification and tier for pattern tracking.

The three-tier chain guarantees that at least one tier produces a parseable verdict for any epic size, trading depth for completion as tiers escalate. The Simulator already runs on opus, so no model escalation is needed.

