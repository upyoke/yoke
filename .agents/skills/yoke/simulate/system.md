# Simulate Phase: System-Wide Simulation

When invoked as `/yoke simulate --system`, run this flow instead of the per-epic flow. This is Ouroboros's system-wide consistency audit.

## S1. Gather System-Wide Context Bundle

Read and assemble all of the following:

- Canonical agent bodies: all `runtime/agents/*.md`
- Claude adapter frontmatter: `.claude/agents/yoke-*.md` (generated views; inspect when adapter drift or hook wiring matters)
- SKILL files: `.agents/skills/yoke/SKILL.md` and all `.agents/skills/yoke/*/SKILL.md`
- Python API surface: the module tree under `runtime/api/` (domain modules, engines, CLI, tools) — this is the literal zero-shell owner of every operation
- Rules files: all `.claude/rules/*.md`
- Documentation: all `docs/*.md`
- Hook wiring: `python3 -m runtime.harness.hook_runner` (shared Claude + Codex dispatch entrypoint), plus the hook entries in `.claude/settings.json` and `.codex/hooks.json`

## S2. Invoke The `yoke-simulator` Subagent

Use this prompt:

```text
Run a system-wide consistency audit for Yoke.

## Mode: SYSTEM-WIDE (Ouroboros)

This is not a per-epic simulation. You are auditing the entire Yoke system for internal consistency — agents, commands, Python owners, rules, hooks, and documentation.

## Canonical Agent Bodies
{contents of each runtime/agents/*.md file, labeled with filename}

## Claude Adapter Frontmatter
{frontmatter blocks from each .claude/agents/yoke-*.md file, labeled with filename}

## SKILL.md Commands
{contents of root SKILL.md and each nested SKILL.md, labeled with path}

## Python API Surface
{selected contents from runtime/api/domain/, runtime/api/engines/, runtime/api/cli/, runtime/api/tools/, labeled with module path — focus on the modules named in SKILL.md operational guidance}

## Rules
{contents of each .claude/rules/*.md, labeled with filename}

## Documentation
{contents of each docs/*.md, labeled with filename}

## Hook Wiring
{hook entries from .claude/settings.json and .codex/hooks.json, plus docstrings from runtime/harness/hook_runner/}

## Instructions
Check these gap categories:
1. Stale agent references
2. Stale SKILL references
3. Cross-agent assumption mismatches
4. Stale hook references
5. Rule-implementation contradictions

Use Grep and Glob to spot-check claims in the codebase.

Produce your gap report. Use [CRITICAL], [WARNING], [NOTE] severity prefixes.
```

## S3. Capture Ouroboros Reflections

Search the Simulator response for `---REFLECTION-START---` and `---REFLECTION-END---`. If found, insert each reflection entry into the DB via `ouroboros insert-entry`. If not found, continue silently.

## S4. Save The Gap Report

Write the Simulator's gap report to:

```text
ouroboros/health/simulation-system-{YYYYMMDD}.md
```

This path is local, generated, and gitignored.

Do not stage or commit this report.

## S5. Parse And Display Summary

Count `[CRITICAL]`, `[WARNING]`, and `[NOTE]` lines in the saved report and display:

```text
Ouroboros system-wide simulation complete: {X} critical, {Y} warnings, {Z} notes

{if X > 0:}
Critical gaps found. File tickets via /yoke idea and fix through the normal pipeline.

{if X == 0 and Y > 0:}
No critical gaps. Review warnings and file tickets for any that need attention.

{if X == 0 and Y == 0:}
Clean simulation. Yoke's components are internally consistent.

Full report: ouroboros/health/simulation-system-{YYYYMMDD}.md
```

Do not offer auto-fix for system-wide simulation.
