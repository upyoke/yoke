---
name: doctor
description: Run the Ouroboros health scan for Yoke or a specific project. Checks backlog consistency, GitHub sync, worktrees, docs drift, dispatch chains, agents, hooks, and project-specific diagnostics.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[project] [--fix] [--file path]"
---


# /yoke doctor

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

Read [run.md](run.md), then [notes.md](notes.md) before any `--fix`.
N/A is never a pass; report its reasons and count.
