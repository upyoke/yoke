---
name: simulate
description: Run the Simulator to trace cross-task integration paths and find gaps. Auto-detects plan phase or integration phase. --system for Ouroboros system-wide consistency audit.
argument-hint: "{epic-ref} [--auto-fix] | --system"
---

# /yoke simulate {epic-ref} | --system

Operator decisions in this skill always use an Inbox decision request. Follow
`.yoke/docs/sessions/inbox.md#operator-questions`: workers route through steering
when a seat is live, otherwise use `decision-requests ask` directly; raise the
question in chat and record the answer with resolve. Use plain language, give the context needed to decide, name things in words (any id follows the name in parentheses), and keep the question very short.


Pass the epic as PREFIX-N. No `yoke simulate` command exists; this skill
persists Simulator output.

Phase map: read [system](system.md) for `--system`; else [epic-flow](epic-flow.md),
[dispatch-prompts](dispatch-prompts.md), then [autofix-loop](autofix-loop.md).
