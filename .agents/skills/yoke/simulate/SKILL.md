---
name: simulate
description: Run the Simulator to trace cross-task integration paths and find gaps. Auto-detects plan phase or integration phase. --system for Ouroboros system-wide consistency audit.
argument-hint: "{epic-id} | --system"
---

# Internal sub-skill -- called by conduct. Not operator-facing.

# /yoke simulate {epic-id} | --system

Trace cross-task execution paths across an entire epic to find integration gaps that per-task testing misses. Or, with `--system`, run an Ouroboros system-wide consistency audit across all of Yoke's components.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{epic-id}` — Epic ID (the numeric `id` of the epic backlog item, which equals the `epic_id` foreign key in `epic_tasks`)
- `--system` — Run a system-wide consistency audit (no epic name required). Checks all agents, SKILLs, scripts, rules, hooks, and docs for internal consistency. Produces a report only — no auto-fix.
- `--force-integration` — Run integration simulation even if some tasks are incomplete (traces completed work only)

## Philosophy

**Blast radius via discovery.** When gathering context for the Simulator, include grep-based discovery of actual consumers and callers — not just the file lists from the Architect's plan. The Simulator's value is finding what the plan missed.

**Events table for forensic context.** For integration simulations, the events table captures tool call history, anomaly patterns, and timing from task execution. Include `yoke events query --item {N}` in investigation when diagnosing cross-task gaps against actual code.

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. The simulation report is the cold-start for the Architect's autofix pass. Every gap must include verified file paths, the specific mismatch, severity, and concrete fix guidance so the Architect can fix each gap mechanically.

## Steps

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active simulate). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode simulate
```

1. **If `--system` is present, read and follow [system.md](system.md).**
 This phase owns the Ouroboros-wide audit flow and its report output.

2. **Otherwise, read and follow [epic-flow.md](epic-flow.md).**
 This phase covers epic existence checks, phase detection, context gathering, reflection capture, report persistence, and the main simulation summary.

3. **Use [dispatch-prompts.md](dispatch-prompts.md) when invoking the Simulator.**
 It contains the canonical prompts for plan simulations and both integration modes.

4. **If fixable gaps remain and the operator approves auto-fix, read and follow [autofix-loop.md](autofix-loop.md).**
 This phase owns Architect fix mode, DB writes, change summaries, and the capped re-simulation loop.

## Notes

- The Simulator subagent is read-only — it cannot write or edit files. The simulate command saves the report.
- The Architect subagent is also read-only — it produces modified task content as output, but the simulate command is responsible for writing content to the DB.
- Plan simulation is the cheapest point to catch bugs — no code has been written yet, so fixes are cheap.
- Integration simulation catches cross-branch mismatches that per-task testing misses.
- `--force-integration` is useful when most tasks are complete but one is stuck.
- System-wide simulation (`--system`) is an Ouroboros feature. It audits Yoke's own components for consistency drift and produces a report only.
