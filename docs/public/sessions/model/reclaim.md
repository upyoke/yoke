# Reclaim and current calls

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Sessions](../index.md) > Reclaim and current calls
<!-- /yoke:breadcrumbs -->

Ended and terminated sessions have the same reclaim decision (`reason=ended`):
any leftover claim can be reclaimed, even if its heartbeat is recent or it was
parked. Cleanup and its preview select only sessions with neither terminal stamp;
they do not end a terminated session again. The scheduler calls a leftover claim
`claimed_by_ended`; silence alone never makes a held claim assignable.

In-flight means a current open tool call on a running turn, with no terminal
stamp or current native process exit. A call superseded by later tool activity,
a call opened before a recorded park, or a call at least 45 minutes old is no
longer in flight. Heartbeat pulses and running posture alone cannot extend it.
Reclaim, message delivery, vendor-error recovery and fleet reports all read
`session_state.session_in_flight`; claim protection remains independent of it.

**Stale-session thresholds (canonical reference).** The reclaim windows are config-tunable, not code literals. The sweep first selects an occupancy tier:

- `session_stale_ttl_minutes` (default `20`) — the short tier for a session with no active work claim, no session-owned strategy-document claim, and no session-owned coordination lease. One base applies on every harness; transient stop signals attempt only a non-destructive empty-session end.
- `session_stale_ttl_with_holdings_minutes` (default `1440`) — the minimum tier for session-owned strategy-document locks. Active work claims have no inactivity bound. Steering acquire automatically takes over overlapping project or document seats when the holder has ended or terminated, or its process is confirmed gone with no resume in flight. It releases the seat and paired document lock, records the old holder and exit time, and sends that holder a notice to reacquire before steering again. A native-wake worker's normal exit between turns stays protected; heartbeat silence never proves exit. Live holders keep their seats: contact them with `yoke say --session SESSION-ID`. No temporary document seat is needed. A steering seat frees another session's claim without ending it: `yoke claims work release --claim-id N --reason R`. `yoke sessions terminate SESSION-ID --reason R` requires the caller to hold a live steering seat on any project in the org; the target may be on any project and may itself hold steering seats. Termination releases every claim the target holds, including its steering seats and their paired strategy-document locks. Without a seat it refuses `TERMINATION_AUTHORITY_REQUIRED`; acquire one with `yoke claims steering acquire --project P --reason TEXT` or route via `yoke say --steering`. Operator-driven sessions refuse `TERMINATION_OPERATOR_SURFACE`; release the listed claims instead. It refuses a session a wake is resuming as `TERMINATION_RESUME_IN_FLIGHT` — a `wake_relay` attempt started at or after the recorded native exit that is still open or resumed a process not yet reported exited, within the resume-custody quiet window — because a headless worker's process exits between turns and a message resumes it; `--allow-resume-in-flight` overrides for a deliberate restaff or evidence it cannot resume. Logical stop and physical exit are separate: one bounded TERM/KILL attempt (2-second TERM grace, then up to 2 seconds to verify exit; Claude job-stop command timeout 20 seconds) retains custody on missing/denied/unverified results. Inspect custody and permissions, then repeat the explicit termination command to retry a failed physical reap; pending and verified successful requests are idempotent, with prior failed evidence retained in the existing reap row.
Resolver: `yoke_core.domain.sessions_analytics_core` owns both source thresholds. The sessions-card stale-eligible time is absent while an active work claim protects its holder.

See the [session model](sessions.md) for stored identity and claim fields.
