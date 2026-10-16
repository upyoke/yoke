# Worker recovery when a model is at capacity

The relay's ordinary poll recovers vendor-stopped item workers. An explicit
model-capacity refusal starts a successor immediately. Other overload errors
retain the existing one-, five-, and fifteen-minute retries; exhausting those
retries starts the same recovery. Authentication, quota and client-build errors
retain their own named handling.

The successor uses the worker's current execution level, actor and machine. Placement
excludes the overloaded model across machines, native effort/speed selectors,
and identities the effective published model catalog declares equivalent,
then applies the normal configured quota order, eligibility, spread and headroom
rules. It never moves work to another level automatically.
Keeping the machine pin preserves access to the registered lane and dirty files;
an alternative available only on another machine is refused for steering to handle.

Custody stays with the stopped predecessor until the exact successor registers.
Registration transfers the same exclusive item claim, archives the predecessor's
focus, and queues its native process for termination. The registered lane,
branch, committed and dirty work, path claims, and existing Progress Log are
preserved. The successor's mandate names the provider refusal and directs it to
read that checkpoint and the lane's actual status/log before continuing.

The launch's durable `level_placement.capacity_recovery` names its predecessor,
claim, episode, exclusions and reason. Duplicate relay polls reuse that launch.
Without intervening work, successor failures retain the prior model exclusions,
so two overloaded models cannot bounce the item between them. No recovery
decision depends on event delivery or retention. A predecessor that
has resumed, performed new work, changed actor, or lost custody cannot transfer
its claim. Sessions with more than one holding require steering to restaff them.

Inspect the successor through `yoke session-control launch get LAUNCH-ID --json`.
The fleet report shows a pending successor as relay-owned recovery. If every
other same-level option is blocked, it shows `capacity_recovery_refused` with
`level_no_capacity`, each rejected option and the recovery step. A failed or
expired successor shows `capacity_successor_failed`; the predecessor keeps its
claim. Steering must inspect/reconcile the named launch before restaffing or
deliberately selecting another level. Recovery refusals are stored with the
session's native turn observation, so a vanished event cannot hide them.

Detection follows each harness manifest's `turn_record` capability. The central
recovery handler has no harness branch and can place any eligible same-level
surface. Automatic observation currently uses the declared Codex CLI record
reader. Claude CLI and Cursor CLI declare no reader because their observed
turn endings fire hooks; extracting provider-capacity evidence from those hooks
is a designed deferral until a supported signal is declared. Desktop surfaces
without a verified provider-error record do not inherit their CLI's reader;
steering owns their recovery until that surface declares an observation path.

## Message and survey recovery during a slow read

Inspect the original message with `yoke messages get MESSAGE-ID --json --full`.
`yoke messages acknowledge MESSAGE-ID` settles receipts addressed to both your
session or steering seat and your actor. Other recipients remain unchanged.
Repeated processing of the same wake failure reuses its uncancelled notice
before resolving recipients again. A changed failure or a cancelled notice
still follows the ordinary delivery path, including its retry and ownership
checks. Narrow recipient anchors load only the sessions they address; explicit
ended-session addresses and deliberate broad selectors retain their semantics.

If a survey command loses its response, read its saved state with
`yoke direct-workflow conflict-survey status ITEM --json --full` before retrying
the write. The status rechecks live claims and overlaps; an earlier saved survey
alone does not clear that gate. Survey content reads exclude terminal and frozen
items before fetching their documents, while every eligible overlap still counts.

## Relay freshness during queue draining

A one-second drain cadence speeds up admission without shortening the relay
liveness window. Heartbeats retain at least two ordinary poll intervals and
any longer active launch lease, so a healthy persistent relay keeps peer
brokers from taking its work. A relay that stops reporting still expires;
shorter polling does not reset message attempts or bypass native custody.
