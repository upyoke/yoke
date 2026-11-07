# Engineer — Live-State AC Execution Semantics

Read when an acceptance criterion names a live database, a deployment, an
external service or other shared mutable state.

- `[READ-ONLY]`: inspect and verify only. A mismatch is the deliverable: record
  observed against expected state and stop. Never repair live state under this
  tag.
- `[APPLY-MUTATION]`: change state only through its sanctioned write path —
  the migration history (read `.claude/agents/references/engineer/migration-protocol.md` first), a registered
  `yoke` command, or the declared deployment pipeline — then verify the result.
- Untagged: treat as `[READ-ONLY]` and report the ambiguity so the parent can
  ask the Architect.
