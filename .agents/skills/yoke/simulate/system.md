# Simulate Phase: System-Wide Simulation

When invoked as `/yoke simulate --system`, run this flow instead of the per-epic flow. This is Ouroboros's system-wide consistency audit.

## S1. Gather System-Wide Context Bundle

Read and assemble all of the following:

- Rendered agent prompts: all `.claude/agents/yoke-*.md`, `.codex/agents/yoke-*.toml`, and `.cursor/agents/yoke-*.md`
- Claude adapter frontmatter: `.claude/agents/yoke-*.md` (generated views; inspect when adapter drift or hook wiring matters)
- SKILL files: `.agents/skills/yoke/SKILL.md` and all `.agents/skills/yoke/*/SKILL.md`
- Python API surface: the installed module families (`yoke_core.domain`, `yoke_core.engines`, `yoke_core.cli`, `yoke_core.tools`, `yoke_contracts`, `yoke_cli`, `yoke_harness`) — this is the literal zero-shell owner of every operation
- Rules files: all `.claude/rules/*.md`
- Documentation: all `docs/*.md`
- Hook wiring: `yoke hook evaluate` (shared Claude + Codex dispatch entrypoint), plus the hook entries in `.claude/settings.json` and `.codex/hooks.json`

## S2. Invoke The `yoke-simulator` Subagent

Use this prompt:

```text
Run a system-wide consistency audit for Yoke.

## Mode: SYSTEM-WIDE (Ouroboros)

This is not a per-epic simulation. You are auditing the entire Yoke system for internal consistency — agents, commands, Python owners, rules, hooks, and documentation.

## Canonical Agent Bodies
{contents of each rendered agent prompt, labeled with its installed filename}

## Claude Adapter Frontmatter
{frontmatter blocks from each .claude/agents/yoke-*.md file, labeled with filename}

## SKILL.md Commands
{contents of root SKILL.md and each nested SKILL.md, labeled with path}

## Python API Surface
{selected contents from yoke_core.domain, yoke_core.engines, yoke_core.cli, and yoke_core.tools, labeled with module path — focus on the modules named in SKILL.md operational guidance}

## Rules
{contents of each .claude/rules/*.md, labeled with filename}

## Documentation
{contents of each docs/*.md, labeled with filename}

## Hook Wiring
{hook entries from .claude/settings.json and .codex/hooks.json, plus hook-handler docstrings}

## Instructions
Check these gap categories:
1. Stale agent references
2. Stale SKILL references
3. Cross-agent assumption mismatches
4. Stale hook references
5. Rule-implementation contradictions

Use Grep and Glob to spot-check claims in the codebase.

Produce your gap report. Use [CRITICAL], [WARNING], [NOTE] severity prefixes.
Begin with exactly this two-line identity block before the report:
`SIMULATION: CLEAN` or `SIMULATION: GAPS FOUND`, then `SCOPE: SYSTEM`.
```

## S3. Capture Ouroboros Reflections

The PostToolUse Agent-tool hook (`yoke_core.domain.reflection_capture_hook`)
captures and persists the Simulator's reflection block automatically. Do not
parse or insert reflections manually. If the Simulator emits no reflection
entries, continue silently.

## S4. Save The Gap Report

Persist the Simulator's gap report through the owned helper. It creates
`ouroboros/health/` when missing — do not assume a prior doctor or
simulate run left the directory behind:

```bash
printf '%s' "{simulator gap report}" | python3 -m yoke_core.domain.persist_system_simulation
```

The helper writes `ouroboros/health/simulation-system-{YYYYMMDD}.md`.
This path is local, generated, and gitignored.

Do not stage or commit this report.

## S5. Parse And Display Summary

Count `[CRITICAL]`, `[WARNING]`, and `[NOTE]` lines in the saved report and display:

```text
Ouroboros system-wide simulation complete: {X} critical, {Y} warnings, {Z} notes

{if X > 0:}
Critical gaps found. File work items via /yoke idea and fix through the normal pipeline.

{if X == 0 and Y > 0:}
No critical gaps. Review warnings and file work items for any that need attention.

{if X == 0 and Y == 0:}
Clean simulation. Yoke's components are internally consistent.

Full report: ouroboros/health/simulation-system-{YYYYMMDD}.md
```

Do not offer auto-fix for system-wide simulation.
