---
name: simulate
description: Run the Simulator to trace cross-task integration paths and find gaps. Auto-detects plan phase or integration phase. --system for Ouroboros system-wide consistency audit.
argument-hint: "{epic-ref} [--auto-fix] | --system"
---

# /yoke simulate {epic-ref} | --system

Pass the epic as PREFIX-N. No `yoke simulate` command exists; this skill
persists Simulator output.

```text
yoke sessions touch --mode simulate
```

Phase map: read [system](system.md) for `--system`; else [epic-flow](epic-flow.md),
[dispatch-prompts](dispatch-prompts.md), then [autofix-loop](autofix-loop.md).
