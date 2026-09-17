# /yoke refine final phase — policy-aware path closure

## Final phase — Policy-Aware Path Closure (before status advance)

Refine MUST NOT advance from `REFINE_ACTIVE_STATUS` to
`REFINE_TARGET_STATUS` until every enabled axis is complete. Run the readiness
check once more after critique-driven updates and before the status mutation
in step 9:

```bash
yoke readiness check PREFIX-N
```

The exit condition is the same as idea's policy-aware path closure:

- When File Budget is enabled, every file the implementer will edit is
  enumerated in `## File Budget`, one path per line, with current line count,
  remaining headroom against 350, and an at-or-over-limit flag. **Counts and
  approximations ("roughly 30 files", "every caller", "all importers") are
  not acceptable** in place of enumerated paths.
- When path claims are enabled, coverage is complete from the enabled File
  Budget or, when budget is off, from the execution artifact/investigation.
- Only when both axes are enabled does this phase require parity between them.
- The readiness check reports `verdict=pass`. A `verdict=unavailable` is not a
  pass: it names checks this host could not perform, and re-running it here
  cannot change that (see [`readiness-repair.md`](readiness-repair.md)).

If the check fails or the spec still contains unexpanded prose substitutes for enumeration, do NOT advance. Either complete the enumeration in this pass or stop and surface the gap to the operator. The boundary gate at advance time exists as a tripwire, not as a fallback for refine skipping closure.

When File Budget is enabled, **only physical files belong in `## File
Budget` list-item backticks.** Function ids (`items.section.upsert`), event
names, command surfaces, and other operational references go in the
surrounding spec prose.

## Multi-turn refine session continuity

Refine writes go to the structured fields the protocol names (`spec`,
`design_spec`, `technical_plan`, `worktree_plan`, `shepherd_caveats`). Those
are intent/design surfaces, not scratchpads for in-flight state. If a pass
spans multiple turns, write checkpoint notes to the item's **Progress Log**;
successor agents use it to learn what is complete, pending, and settled.
