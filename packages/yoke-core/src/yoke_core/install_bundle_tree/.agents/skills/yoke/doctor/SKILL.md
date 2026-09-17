---
name: doctor
description: Run the Ouroboros health scan for Yoke or a specific project. Checks backlog consistency, GitHub sync, worktrees, docs drift, dispatch chains, agents, hooks, and project-specific diagnostics.
argument-hint: "[project] [--fix] [--file path]"
---

# /yoke doctor

Run the Ouroboros system health scan. Checks the Yoke installation for consistency, drift, and breakage. When a project is specified, runs additional project-specific diagnostics. Branded as the **Ouroboros Health Report**.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `[project]` — Target project for project-specific checks. Defaults to the project bound to the checkout you are standing in; a machine that knows no such binding falls back to the seeded self project. Examples: `external-webapp`, `yoke`. The first positional argument that is not a flag is treated as the project name.
- `--fix` — Auto-repair trivial issues (label mismatches, stale dashboards, stale worktree refs). Non-trivial issues are reported only.
- `--file {path}` — Save the report to a custom path (default: `ouroboros/health/health-{YYYYMMDD}.md`)

## Philosophy

**Every check declares what it applies to.** The roster is not one fixed list
shipped everywhere. Each check states its project scope, whether it reads the
target project's source tree, which runtimes it runs under, and which
capabilities it needs; the runner derives the applicable set from the live
context. See `## Health Checks` in AGENTS.md for the model.

**Report "not applicable" honestly.** A relayed run executes the
control-plane checks on the server, which holds no source tree. The run
then composes: each check the server answered `N/A` *for want of a
checkout* is re-run against this machine's checkout for the target
project, and the local verdict replaces the relayed one. What stays
`N/A` is what nothing could honestly answer — most often no checkout
mapped for that project on this machine — and it carries its reason in
the `## Not Applicable` section rather than counting as a pass. When you
relay a report, relay the not-applicable count too: `N passed` does not
mean the source tree was inspected.

**Project-local checks.** A project's own checks live in its `.yoke/doctor/`
folder and are discovered pytest-style by a runner that holds the checkout.
They appear in the report exactly like engine checks. A check module that
fails to import is reported as `HC-project-check-discovery` FAIL. Yoke's own
source-dev checks — agent and adapter drift, hook parity, skill and doc
consistency, tier discipline, code-doctrine scans — live there rather than in
the engine. They run wherever the target project's checkout is mapped, on
either transport; a run targeting a project this machine holds no checkout
for carries none of them.

**Events table as health signal.** The events table captures anomaly patterns across all agent sessions. Include `yoke events anomalies --since "24 hours ago"` in the diagnostic context. Elevated anomaly counts or recurring `nonzero_exit` patterns on specific scripts are health signals.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| Run | `/yoke doctor` was just invoked | [`run.md`](run.md) |
| — Interpret the result | You need the exit-code contract, `--fix` scope, or a specific check's caveat | [`notes.md`](notes.md) |

## Start

Read [`run.md`](run.md) and follow it.
