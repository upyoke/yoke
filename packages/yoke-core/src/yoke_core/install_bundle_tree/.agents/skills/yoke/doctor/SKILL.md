---
name: doctor
description: Run the Ouroboros health scan for Yoke or a specific project. Checks backlog consistency, GitHub sync, worktrees, docs drift, dispatch chains, agents, hooks, and project-specific diagnostics.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[project] [--fix] [--file path]"
---


# /yoke doctor

Run the Ouroboros Health Report for the caller's project or an explicit first
positional project. Use `--fix` for deterministic repairs; other failures remain
reported. `--file path` explicitly saves the report.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Checks declare project scope, source-tree access, runtimes and capabilities;
the runner derives the applicable roster from live context. Project-local
`.yoke/doctor/` checks use pytest-style discovery; an import failure is
`HC-project-check-discovery` FAIL.

HTTPS executes control-plane checks remotely and re-runs source-missing N/A
checks against the mapped local checkout. Remaining N/A retains its reason
and count; it is never a pass or evidence that source was inspected.
Include `yoke events anomalies --since "24 hours ago"` as diagnostic context.

Each check has a 45-second budget; timeout is incomplete FAIL evidence.
HTTPS chunks have 60 seconds/two attempts and a 15-minute remote-roster
deadline. Preserve partial reports/error identities; after provider recovery
retry the named check with `yoke watch doctor -- --only <slug>`.
Project checks use bounded I/O helpers.

## Phase map — read before acting

| Phase | Read |
|---|---|
| Claim, execute, repair and release | [run.md](run.md) |
| Exit codes, repair limits and specific caveats | [notes.md](notes.md), before choosing repair |

Start with run.md; read notes.md before a repair.
