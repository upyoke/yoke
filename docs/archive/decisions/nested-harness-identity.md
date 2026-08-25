# A nested harness resolves its own identity, or none

## What happened

A `codex exec` run was launched from inside a Claude session's shell. It
registered its own session row through its own hooks, printed its own
session id in its own orientation block, and then answered
`yoke sessions identity` with the *Claude* session — full lane, project,
and actor of the conversation that launched it. A Cursor agent launched
the same way did the same thing. Neither was a near miss: each would have
claimed items, transitioned lifecycle, and written evidence under another
session's authority, and nothing in the output said so.

The cause is ordinary inheritance. A harness stamps its session id into
the environment of every process it starts, and every process those start
in turn inherits it — including another harness. The ambient chain read a
fixed list of variables in a fixed order, and `CLAUDE_CODE_SESSION_ID`
came before Codex's variables, so a Codex child answered with the value
its parent exported.

Reading more of the environment cannot fix this. Both variables are
present in a nested child, and neither records which process exported it;
the order between them is a guess that happens to be right for one
nesting direction and wrong for the other.

## The decision

**The process tree names the owning harness, and only that harness's
channels may answer.** The nearest harness ancestor is the harness this
process actually runs under. Nothing below it can inherit that fact, and
nothing can make it stale.

So the chain now reads:

1. `YOKE_SESSION_ID` — Yoke's own stamp, what an explicit `--session-id`
   propagates for one invocation. A deliberate operator override, never
   something a harness exported, so it wins outright.
2. The owning family, from the process tree. Only its channels are
   consulted: its variables, its anchor, and — for the one family that
   stamps no variable — its conversation map.
3. With no harness ancestor at all, the family-blind chain, unchanged.

Step 3 matters as much as step 2. An operator terminal, a CI runner, and
a process reparented after its harness exited all have no harness above
them, so nothing was inherited from anybody and an environment variable
is the best evidence available. Scoping there would refuse identity to
the cases that were never ambiguous.

## Refusing beats borrowing

A family that stamped nothing this process can read resolves to no
identity, even though a variable from another harness is sitting right
there. That is deliberate, and it is the same rule the anchor registry
already follows for a contended pid: an unresolvable identity is a gap to
report, a confidently wrong one is a correctness bug. An
`actor_session_missing` refusal is visible and names its recovery. Acting
as another session is not visible at all — which is exactly why this
defect survived long enough to be reproduced on two harnesses.

The denial diagnostics name the owning family for the same reason. A
reader who sees `process_family=codex` beside a populated
`env:claude-code` can tell at a glance that the inherited value was
passed over on purpose rather than missed.

## What this does not change

- A top-level session of any harness resolves exactly as before: its own
  family is the owning one, and its own variable answers.
- A launched Claude worker still resolves through
  `CLAUDE_CODE_SESSION_ID`. Its pooled host belongs to the Claude family,
  and that variable remains the only per-conversation identity reaching
  it — see
  [`launched-worker-ambient-identity.md`](launched-worker-ambient-identity.md).
- A Codex subagent still reads the parent thread before its own, because
  only the parent is registered. Family scoping picks *which* family
  answers; the order inside a family is unchanged.
- The anchor walk still stops at a multiplexed host. That walk asks which
  pid can name one session; the family walk asks which harness owns the
  process, and a shared host answers the second question even though it
  can never answer the first.

## Cost

The family walk reads the process table once per process and is
remembered for that process's life, because a process's ancestry cannot
change while it runs. Identity resolution therefore costs at most one
`ps` per process rather than one per call — and the anchor walk it
often replaces was already paying that price.
