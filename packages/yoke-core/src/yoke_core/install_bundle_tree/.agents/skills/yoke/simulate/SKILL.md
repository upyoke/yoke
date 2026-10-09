---
name: simulate
description: Run the Simulator to trace cross-task integration paths and find gaps. Auto-detects plan phase or integration phase. --system for Ouroboros system-wide consistency audit.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{epic-ref} [--auto-fix] | --system"
---


# /yoke simulate {epic-ref} | --system

Harness slash skill; operators may invoke either epic simulation or the system
audit. There is no terminal `yoke simulate` adapter. Conduct may invoke the
epic flow internally. Trace cross-task plans or actual lane code
through the read-only Simulator.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Use a complete public epic ref. Task states auto-detect plan or integration;
`--force-integration` traces completed work and excludes named incomplete tasks.
`--auto-fix` accepts plan fixes and re-simulations; otherwise follow the loop's
approval points. Code gaps return for an amend cycle. `--system` requires a Yoke
source checkout and produces a consistency report only.

The Simulator and Architect are read-only; the dispatching skill persists
reports and returned plans. Discover actual callers/consumers alongside planned
files. For code-gap forensics use `yoke events query --item PREFIX-N`. Findings
name verified paths, mismatch, severity and concrete fix guidance; link evidence.

## Phase map — read before the governed action

| Phase | Read |
|---|---|
| System audit | [system.md](system.md): source guard and report-only guidance |
| Epic simulation | [epic-flow.md](epic-flow.md): phase gates, context, persistence and summary |
| Simulator dispatch | [dispatch-prompts.md](dispatch-prompts.md): common contract and selected mode |
| Approved fix loop or `--auto-fix` | [autofix-loop.md](autofix-loop.md): capped fixes and caller outcomes |

Stamp the mode, then follow the applicable phase:

```sh
yoke sessions touch --mode simulate
```
