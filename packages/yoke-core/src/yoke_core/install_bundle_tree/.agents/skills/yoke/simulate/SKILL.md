---
name: simulate
description: "Trace an epic's cross-task integration paths for gaps, or audit the system with --system."
argument-hint: "{epic-ref} [--auto-fix] | --system"
---

# /yoke simulate {epic-ref} | --system

Pass the epic as PREFIX-N. No `yoke simulate` command exists; this skill
persists Simulator output.

`--system` needs a Yoke source checkout: follow
`docs/source-dev/system-simulation.md` and report only; without one, stop.

Phase map: [epic-flow](epic-flow.md),
[dispatch-prompts](dispatch-prompts.md), then [autofix-loop](autofix-loop.md).
