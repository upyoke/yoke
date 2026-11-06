# Session state glossary

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Session state glossary
<!-- /yoke:breadcrumbs -->

Session ownership and execution answer separate questions. Read these facts
together to understand a session; an active claim alone does not prove progress.

## Independent session facts

| Term | Meaning |
| --- | --- |
| Presence | `present` unless end stamps or unsuperseded native process death prove `ended` or `gone`. A later tool call proves presence again; heartbeat alone does not. |
| Activity | `working`, `between_turns`, or `silent`, based on tool activity and turn posture. The project idle threshold defaults to 20 minutes. |
| Intent | An explicit pause: `parked` or `awaiting`, with a reason; otherwise `none`. Between turns does not mean parked. |
| Custody | Active holdings and whether automatic reclaim is eligible, with the policy reason. Work claims protect their holders regardless of activity age. |
| Next actor | Who can act next, with a reason and state time. Actors are `this_session`, `operator`, `parent_or_steering`, `another_item`, `ci_or_deploy`, and `nobody`. |
| Reclaimable session | A session eligible for automatic cleanup. The legacy command selector calls this `stale`; silence and process absence alone do not release a claim. |

See the [session model](../sessions/model/sessions.md) for wire fields and the
[sessions guide](sessions.md) for coordination and recovery.

The wire field `session_state` contains `presence`, `activity`, `intent`,
`custody`, and `next_actor`. Intent includes `state`, `reason` and `awaiting_who`;
custody includes `holds`, `holds_work_claim`, `reclaimable` and `reason`;
next actor includes `actor`, `reason` and `since`. A pending decision names its active human audience; an unsatisfied dependency names
another item; a running CI or release names CI or deployment. Otherwise a live
session can continue, and unclaimed ready work needs parent or steering direction.
A parked session keeps its quiet reason and needs direction unless a durable wait
names another actor. Ended sessions and terminal items have nobody left to act.

`project-policy.session_idle_minutes` defaults to 20 and measures tool silence.
Boot preserves the configured value when renaming the earlier steering setting.
A current running open call excuses silence for at most 45 minutes, the shared
watcher ceiling. An unfinished call alone never proves a running process.
Consumers tolerate an absent `session_state` when connected to an older server.
