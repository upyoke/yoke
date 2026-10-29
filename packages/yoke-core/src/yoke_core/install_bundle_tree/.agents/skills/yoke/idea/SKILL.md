---
name: idea
description: Create a new backlog item with a PREFIX-N ID. Infers project, workflow, priority, and flow from context.
argument-hint: "[--dry-run] [--workflow issue|epic|blitz|task] {title}"
---

# /yoke idea [--dry-run] [--workflow issue|epic|blitz|task] {title}

Create one fully specified item. `--dry-run` comes first and writes nothing.

Ask for a missing title or outcome; keep the user's text verbatim. Then
Phase map: read [infer-and-create.md](infer-and-create.md),
[body-and-sync.md](body-and-sync.md) and [notes.md](notes.md).
