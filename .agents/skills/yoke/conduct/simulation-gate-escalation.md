# Conduct — simulation result

Identity or receipt failure: cleanup HALTED.

## CLEAN

Run each still-owed parent QA case, then:

```text
yoke lifecycle transition PREFIX-N --from LIVE_STAGE --to HANDOFF_STAGE --reason "Conduct: tasks reviewed and verified integration simulation" --json
```

Follow [shared handoff](../shared/stage-handoff.md).

If your launch instruction is a single-item mandate for this item, keep the
claim and run `/yoke {next_skill_id} ITEM` now: read and follow the next
bound skill in this turn. Otherwise show the next-skill line and release
the claim. A transition's `level_change` handoff takes precedence: release,
launch the returned successor, and end; follow `.yoke/docs/agents/levels.md`.


## GAPS FOUND

1. PROCEED, zero CRITICAL: file WARNING (medium) and NOTE (low) items via
   [Idea](../idea/SKILL.md) with the exact target project, then:

```text
yoke conduct epic proceed-triage-handoff --epic PREFIX-N --recommendation PROCEED --gap-summary "{BOUNDED_GAP_SUMMARY}" --filed-items {COMMA_SEPARATED_PUBLIC_REFS}
```

After a successful `proceed-triage-handoff`, apply the same claim and
next-skill rule above; the command retains a single-item mandate claim
unless a `level_change` requires a successor.

2. --no-auto-fix: halt.
3. Else run [Simulate's auto-fix loop](../simulate/autofix-loop.md),
   caller=conduct. AUTOFIX_CODE_GAPS: one [amend cycle](simulation-autofix-verification.md).
   AUTOFIX_CLEAN: go to CLEAN. AUTOFIX_HALTED: cleanup HALTED.
   AUTOFIX_NOT_REQUIRED: branch 1 if PROCEED with zero CRITICAL, else halt.
