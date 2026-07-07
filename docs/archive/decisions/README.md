# Decisions

This directory is the durable home for architectural-why entries. Each entry
has a short topic-based slug so callers can link to the reasoning without
reaching into backlog history.

## When to add an entry

Add a new decision document when:

- A non-obvious architectural choice is worth explaining to a future reader,
  and the code itself cannot tell the full story.
- You are retiring a surface or pattern and the durable reasoning for the
  switch deserves a stable home separate from any specific change set.

Do **not** add an entry for ephemeral work: short refactors, routine bug
fixes, or anything whose motivation is already self-evident from the code.

## Format

Each file is a self-contained Markdown document:

```md
# Short topic line

## Context

Why the question arose. What alternatives existed.

## Decision

What we chose and why.

## Consequences

What changes because of this decision — APIs, migrations, invariants, or
follow-on work.
```

Slugs are topic-based (`virtual-body-field.md`, `zero-shell-contract.md`) —
no ticket numbers, no dates. The document must stand alone.
