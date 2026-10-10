# Conduct — bounded output retries

These counters are separate from entry-gates.md's configurable implementation
attempt budget. A real FAIL increments the implementation attempt; missing
output increments only the appropriate output counter.

```text
MAX_TESTER_REPROMPTS=2
MAX_SIMULATOR_REPROMPTS=2
```

## Tester

Initial full shared prompt uses complete size-gated diffs. No durable review
and no clear text verdict: retry1 minimal shared variant/default model, retry2
minimal/shared descriptor escalation. Preserve task/lane/QA and file-backed
diffs; capture reflections/artifacts and parse after each return. After both
retries, [dispatch-context-verify.md](dispatch-context-verify.md) is the explicit
Thin Conduct exception. It still requires a truthful durable verdict; an
inconclusive or blocked check cannot become PASS.

## Simulator

Default compressed two-phase; standard only sim_force_standard_integration=true.
Require both verdict and public EPIC attestation. Missing result classifies as
context_exhaustion when <500 chars, mid-thought/tool fragments or exploration
without report; structured content missing either header is formatting_omission.
Ambiguous defaults to formatting_omission.

Retry1 formatting omission demands the two-line block first; context exhaustion
uses compressed context with aggressive two-phase constraints. Retry2 uses
ultra-compressed overlap/dependency/one-line-task context, required shim/commit
evidence, hard no-tool and maximum3 gaps. Every attempt retains exact epic,
resolved worktree authorities and before-dispatch identity check. After two
retries HALT with classification/tier evidence and Ouroboros; never manufacture
CLEAN or simulate directly. Read [simulation-gate-criteria.md](simulation-gate-criteria.md).

Architect iteration budget belongs solely to
[Simulate's auto-fix loop](../simulate/autofix-loop.md); do not define another.
