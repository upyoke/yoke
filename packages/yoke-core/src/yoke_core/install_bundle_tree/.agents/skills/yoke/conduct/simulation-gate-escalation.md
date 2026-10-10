# Conduct — simulation result branches

## Pre-Branch HALT Conditions

_epic_ref is empty, output retries exhausted, wrong-epic body, missing-epic body,
unverified/mismatched receipt or failed readback goes directly to cleanup HALTED.
Preserve exact returned code/message, refs and recovery. No local verdict branch
or automatic retry of an uncertain write. Persistence is not an auto-handoff.

## CLEAN: actual gates, then handoff

Read parent requirements. Complete each still-owed native case with its exact
subject and current candidate; do not blanket-credit command/Browser cases from
task passes or simulation. The simulation requirement is already credited by
its verified receipt, never another manual run. Aggregate evidence applies only
where that requirement's declared policy actually permits it.

Re-read pin/live status and require all tasks reviewed/done, current integration
CLEAN receipt and no remaining blocking parent requirement. Resolve the next
declared target at this binding's handoff; require correct live source. Registered
lifecycle transition enforces claim, status/QA/approval and immutable pin gates:

```text
yoke workflows item get PREFIX-N --json
yoke lifecycle transition PREFIX-N --from LIVE_STAGE --to HANDOFF_STAGE --reason "Conduct: tasks reviewed and verified integration simulation" --json
yoke items get PREFIX-N status --json
```

Verify the returned/live stage equals HANDOFF_STAGE. A refusal preserves claim/
lanes and names its recovery; no scalar status shortcut. Once boundary is verified,
release only the Conduct parent claim still held and verify exact custody:

```text
yoke claims work release --item PREFIX-N --reason "handoff-to-polish" --json
yoke claims work holder-list --session-id-filter {SESSION_ID} --json
```

Use the actual next skill's truthful handoff reason if different. Failed release
is incomplete handoff, not SUCCESS. Fresh item detail plus
[shared handoff](../shared/stage-handoff.md) renders next command. No done-transition,
issue closure, merge or lane removal. Continue cleanup with SUCCESS for this leg.

## GAPS FOUND

Retain full persisted report, severity counts and actual recommendation.

### Branch 1 — PROCEED and zero CRITICAL

File each required WARNING/NOTE follow-up through [Idea](../idea/SKILL.md), with
exact target project, authorized workflow/entry, title budget, execution instructions
and structured spec/GitHub sync. WARNING→medium; NOTE→low. Keep complete refs,
not numeric tails or issue numbers. No cross-project item combining targets.
Complete actual parent evidence gates, then registered PROCEED triage:

```text
yoke conduct epic proceed-triage-handoff --epic PREFIX-N --recommendation PROCEED --gap-summary "{BOUNDED_GAP_SUMMARY}" --filed-items {COMMA_SEPARATED_PUBLIC_REFS}
```

It requires the held epic claim, exact current failed report, authenticated actor,
explicit PROCEED/zero criticals and required follow-ups. Bounded discharge retains
failed attempts/rationale/refs; changed capture/newer attempt invalidates it.
Reserved receipt namespace cannot be forged with section writes. Verify its
handoff and claim-release result; refusal HALTs. Do NOT write `status
reviewed-implementation` manually. No fake passing simulation or skip-deploy.

### Branch 2 — --no-auto-fix

HALT with retained report/lanes and recovery. Do not fall through to auto-fix.

### Branch 3 — CRITICAL or recommendation not PROCEED

Delegate [simulation-autofix.md](simulation-autofix.md), retaining exact parent,
project, registered lanes, max attempts and already persisted report.

**If auto-fix returns `AUTOFIX_NOT_REQUIRED`:** refresh actual report/counts/
recommendation. With zero criticals and PROCEED, execute Branch 1 above, including
the registered PROCEED triage write. NOTE-only with a non-PROCEED or absent
recommendation returns simulation_nonblocking_recommendation_unresolved for
corrected Simulator recommendation or explicit operator triage. Do not manufacture
PROCEED, passing verdict or status.

**If auto-fix returns `AUTOFIX_CLEAN`:** require its final native verified receipt,
then run CLEAN's real parent gates and verified lifecycle/claim handoff. Previous
candidate evidence does not authorize new code.

**If auto-fix returns `AUTOFIX_HALTED`:** preserve report/work and exact diagnostic,
go to cleanup HALTED. Explicit force is a named bypass leg only; never fabricate
completion. Every branch ends at [cleanup-report.md](cleanup-report.md).
