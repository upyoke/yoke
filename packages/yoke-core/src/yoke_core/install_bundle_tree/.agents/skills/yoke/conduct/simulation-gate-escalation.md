# Conduct — simulation result

Identity or receipt failure: cleanup HALTED.

## CLEAN

Run each still-owed parent QA case, then:

```text
yoke lifecycle transition PREFIX-N --from LIVE_STAGE --to HANDOFF_STAGE --reason "Conduct: tasks reviewed and verified integration simulation" --json
yoke claims work release --item PREFIX-N --reason "handoff-to-polish" --json
```

Next command: [shared handoff](../shared/stage-handoff.md).

## GAPS FOUND

1. PROCEED, zero CRITICAL: file WARNING (medium) and NOTE (low) items via
   [Idea](../idea/SKILL.md) with the exact target project, then:

```text
yoke conduct epic proceed-triage-handoff --epic PREFIX-N --recommendation PROCEED --gap-summary "{BOUNDED_GAP_SUMMARY}" --filed-items {COMMA_SEPARATED_PUBLIC_REFS}
```

2. --no-auto-fix: halt.
3. Else run [Simulate's auto-fix loop](../simulate/autofix-loop.md),
   caller=conduct. AUTOFIX_CODE_GAPS: one [amend cycle](simulation-autofix-verification.md).
   AUTOFIX_CLEAN: go to CLEAN. AUTOFIX_HALTED: cleanup HALTED.
   AUTOFIX_NOT_REQUIRED: branch 1 if PROCEED with zero CRITICAL, else halt.
