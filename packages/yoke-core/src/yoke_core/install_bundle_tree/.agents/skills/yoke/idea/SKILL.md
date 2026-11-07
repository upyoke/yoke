---
name: idea
description: "File one fully specified backlog item, inferring project, workflow, priority and flow."
argument-hint: "[--dry-run] [--workflow issue|epic|blitz|task] {title}"
---

# /yoke idea [--dry-run] [--workflow issue|epic|blitz|task] {title}

Create one fully specified item. `--dry-run` comes first and writes nothing.

Ask for a missing title or outcome; keep the user's text verbatim. Ask at
most 3 questions per run; after that guess from evidence, but never guess the
project or skip a gate.

Phase map: read [infer-and-create.md](infer-and-create.md), then
[body-and-sync.md](body-and-sync.md).
