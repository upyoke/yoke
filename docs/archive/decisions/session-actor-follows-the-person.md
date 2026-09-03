# A session's authority follows the person who started it

Yoke sessions run on many machines for many people out of one universe.
Before this change the control plane could not say, of any action taken on
a session, *who* took it — and for a session nobody sat at, it could not
say whose authority the session itself carried. Three gaps produced that,
and they are fixed together because each one alone leaves the answer
unusable.

## The actor is whoever started the chain, not whoever owns the machine

A session a person opens signs in as itself. A session another session
*launched* acts for whoever started that chain, transitively: a steering
seat on one machine that launches a worker on a second makes that worker
the seat's actor, and a session that worker launches inherits the same
actor again. The machine contributes capacity, never identity.

Registration is where that binds.
`yoke_core.domain.session_launch_actor_inheritance` reads
`session_launches.requester_actor_id` — the dispatcher-resolved actor of
the launching session, never a caller assertion — and
`resolve_session_actor_id` prefers it over every other source. The launch
id reaches registration through the same authenticated `yoke_launch` side
channel that carries the launch attestation, so no caller can name an
actor it does not already hold.

The two sources it outranks are exactly the wrong answers for a launched
worker:

- the operating actor of the machine, resolved from its OS login on a
  local universe (`session_actor_binding.resolve_operating_actor`);
- the verified bearer-token actor over https, which on a relayed
  registration is the machine relay's owner.

A launch id that names no readable row **refuses** rather than falling
back to either of those. Falling back is the misattribution this exists to
prevent, and a worker that binds the wrong actor does not fail visibly —
it quietly acts with the wrong person's authority until something it may
not do finally refuses, far from the registration that caused it.

## Every action on a session lands in that session's history

A session's history is the event stream keyed on its own `session_id`.
Everything a session does for itself already landed there; everything done
*to* it was recorded only under the caller's session, so a worker's own
history could not say who woke, held, messaged, or ended it.

`yoke_core.domain.session_action_attribution` writes one
`SessionActionPerformed` row into each target session's history per
dispatched session-affecting call, carrying the **acting** actor as its
`actor_id`, the acting session, the function id, and whether the call
succeeded. Reading "who drove this session" is now a read of that
session's own history:

```
yoke events query --session <target-session-id> \
    --event-name SessionActionPerformed
```

Two rules keep the record honest rather than merely present. A call with
no bound acting actor writes nothing, because the session-actor backfill
would otherwise stamp the *target's* actor on the row and it would read as
the session having done this to itself. And a failure to write the
attribution row never fails the action it describes: the action already
happened, and turning a completed termination into an error would be a
worse lie than a missing row.

`SESSION_ACTION_LABELS` is the single list of what counts as
session-affecting. The attribution writer and the authority check both
read it, so the set that is recorded and the set that is role-checked
cannot drift apart.

## One role check, and refusals that name what is missing

`yoke_core.domain.session_action_authority` owns the whole rule:

| Action | Authority |
|---|---|
| message, wake, keep-alive hold/release, launch | any member of the target's project (`items.write`) |
| terminate a launched worker | the same project membership |
| terminate your own session | the same project membership |
| terminate another actor's interactive session | project `owner` or org `admin` (`project.admin`) |

Driving another person's worker is normal work — with the role. Ending an
interactive session is not: that is a person at a terminal, and stopping
them is administration.

It is applied in two places for one reason. Calls whose payload names the
target session outright (wake, terminate, keep-alive) are checked by the
dispatcher through
`session_action_dispatch_permission`, before the handler runs. A message
resolves its audience by anchor, so the targets do not exist until the
handler has resolved them; `authorize_recipients` therefore applies the
same function per project the audience actually reached. Same decision,
same refusal wording, applied where the targets are known.

Refusals name the actor, the roles it actually holds on that project, and
the action it attempted. "Permission denied" alone sends the reader to the
wrong place: the usual cause is a real member acting on a project they
were never granted, and only the held-role list makes that visible.

## What this does not change

Termination still additionally requires the caller to be in operator mode
or to hold the project's steering claim
(`require_operator_or_steering_authority`). That is a session-posture
requirement, a different axis from the role, and both now apply.
