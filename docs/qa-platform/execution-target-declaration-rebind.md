# Execution-target rebind after a declaration change

A QA requirement stores an immutable execution-target snapshot. Correcting
an environment's declared facts (`hosts.*`, `distribution.*`, `role.production`)
moves that snapshot's digest even when the case still names the same
environment row and the same subject. The snapshot-reuse, retract, and
supersession guards stay as they are: none of them may silently rebind a
row that holds a verdict.

`yoke qa requirement rebind-target` is the missing act. It points the row
at the live declaration of **the same environment identity**, keeps the
recorded runs and verdict, and writes `rebound_at`, `rebound_from_digest`,
`rebind_rationale`, and `rebind_actor_id` so a later reader can see exactly
what moved and why. A pass recorded against the previous digest still
proves the row after that rebind.

```text
yoke qa requirement rebind-target --requirement-id N --rationale '...'
```

It is not a waiver and not a re-run. Teach it when the stored target and
the live target resolve to the same environment row and subject and differ
only in declared facts. A different environment, a different deployment
receipt, or a different subject is a genuinely different target: this
command refuses, and the recovery is a fresh execution or sanctioned
retirement/supersession.

## Do not strand the digest silently

`yoke projects environment-settings merge` knows which environment it is
writing. When a written path is an input to the execution-target digest and
requirements are bound to the digest that write will move, the merge
reports the bound count and item ids and refuses unless
`--acknowledge-stranded-evidence` is set. The write is cheap; discovering
the fallout one close-out refusal at a time is not.

## Snapshot reuse names this recovery when it applies

`require_existing_target` still refuses to reuse a row bound to a different
digest. When the mismatch is a declaration correction of the same
environment, that refusal names `yoke qa requirement rebind-target` and the
condition under which it applies. When the identity actually changed, it
still names a fresh execution or sanctioned retirement/supersession.
