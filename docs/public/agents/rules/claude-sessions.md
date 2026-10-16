# Claude session rules — the deep home

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Claude sessions
<!-- /yoke:breadcrumbs -->

Read the applicable section before its action. Startup rules carry short
normative rules; shared authority remains in AGENTS and the linked operation
homes. This reference governs Claude main sessions and dispatched subagents.

## Hook schema

Every settings.json hook entry uses nested `{hooks: [{type, command}]}`;
one malformed entry can disable the entire subtree. Install hook_schema
validation refuses before checkout mutation; HC-project-hook-config-validity
checks installed Claude/Codex/Cursor files. Diagnose with
`yoke watch doctor -- --only project-hook-config-validity` and Claude startup
Settings Error. Preserve all-or-nothing schema, not per-entry partial repair.

## Session end, revival, and reactivation

Authorized explicit physical stop uses `yoke sessions terminate SESSION-ID
--reason R`; read its --help. Logical end/cancellation and physical exit are
separate. Relay TERM gets 2 seconds, then KILL and up to 2 seconds matching
process/group verification; Claude native job-stop has separate 20-second bound.
Missing custody/signal permissions/unverified exit stays unresolved. Inspect
custody/permissions and repeat explicit command for failed reap; pending/success
is not duplicated, failures remain evidence. Adoption failure/child survival
retains supervision/group custody. Shared desktop hosts follow manifest's
operator-managed limits.

Transient SessionEnd (sleep/reload/disconnect/idle) proves no permanent death.
Stop/end uses non-destructive end_session_if_empty: no claims released; skip
has_claims, has_document_locks, keepalive_held, wake_delivery_in_flight or
launch_delivery_pending. Active work claims stay protected regardless of
heartbeat age/park/process death; scheduler reads claimed_by_other_live and
report excludes item from available. Holdings TTL cannot reclaim active work.
Explicit claim-releasing end releases liveness-bound claims with evidence;
checkpoint budget never blocks ending. Ended sessions can explicitly acquire.

Keepalive is a caller-owned bounded control-plane lease for claimless target:
`yoke sessions keepalive hold SESSION-ID --reason R --seconds N`, release with
keepalive release or expiry. Target tool calls neither set nor clear it.
Park is self-declared and its next tool call clears it. Keepalive prevents idle
reap, never authorized termination. Claimless stale cleanup uses heartbeat;
other holdings may use configured TTL.

Relay liveness needs machine-observed pid/start/state, no record means no death
claim. A named launched-process exit applies immediately; hook-anchor-only
observation waits TTL. Gone unregistered launch with retained supervision closes
native_exited_unregistered with exit/capture, not registration timeout.
Control plane ends process_verified_dead/cancels pending mail only with no
holdings, no park and no real steering-reply wait. claims_held/parked/
awaiting_seat_reply skips store observation and retain claims/relay record;
terminal report is not a question. Teardown still requires explicit authority.

Death stamp is native exit time or first same-process observation; later actual
exit time corrects it. Different newer process may replace observation; older
process death cannot overwrite newer evidence. Later heartbeat/tool/episode
activity supersedes it; visible live native is never dead. Probe also checks
zombie state: retained pid/start alone is insufficient. Measured clean exit
under park/armed-landing wait reports that expected wait; nonzero/unmeasured
exit is gone. message_stopped surfaces say process-exited/message-to-resume,
then resuming-now once wake answers. Only unresumable surfaces require deliberate
termination if dead; resuming refuses TERMINATION_RESUME_IN_FLIGHT.

Claude spare cleanup is vendor-owned: childless, older than idle threshold,
unchanged job and not newest warm-pool spare; control plane confirms ended
session, then Claude's job-id stop path. Direct signal only if vendor already
reports stopped, avoiding vendor crash restart. Reclaim emits
HarnessSessionNativeHostReclaimed with pid/age/resident size.

Every hook event can reactivate an ended row, including Pre/PostToolUse when
no new prompt follows sleep. Registration state probe clears ended_at, starts
episode and conditionally restores released claims. Local transport owns local
registration; HTTPS server evaluation owns relayed registration. No manual
registration recipe is needed during ordinary launch/re-entry.

SESSION_ENDED refusals from touch/acquire/checkpoint share stored-identity
recovery renderer. Follow its populated sessions-begin command using stored
requested identity, not a guessed provider/model. Reacquire only for prior
session_ended release within session_reactivation_reacquire_window_s (default
300s) and no conflicting active holder, transactionally emitting
SessionReactivationReacquiredClaims. Conflict produces advisory instead;
explicit recovery is `yoke claims work acquire --item PREFIX-N --reason
session-reactivation-recovery`.

Slim SESSION RESUMED block appears once per cycle on next Claude UserPromptSubmit
or Codex SessionStart: prior targets and reacquire outcome, 5–8 lines, marked
HarnessSessionResumeBlockShown; full orientation is not repeated.

## Session identity spans episodes

Same conversation retains session_id across transient end/resume. Every
reactivation emits HarnessSessionResumed, including claim-free released-count 0;
claim advisories/receipts remain conditional. Envelope names session_id,
prior_release_reason=session_ended, released_claim_count/reacquired_count/
conflict_count and claim_details episode_scope inherited/reacquired/conflict.
One boundary event supports audit without inspecting fresh-start payload.

Work/coordination authority intentionally survives episode boundaries.
Item-owned strategy-document claim authority is owner_item_id (registration
session is provenance); owning item work claim restores access. Session-owned
document lock is session authority: non-destructive end skips it, explicit
release end removes it. Stale sweep cannot release it while active work protects
the session.

`yoke events query --session SESSION-ID --current-episode` uses latest
HarnessSessionResumed/Started; session is required, absent boundary yields empty,
other filters compose AND. elided_prior_episode_rows says older matching evidence
was hidden: nonzero count plus empty rows requires read without flag, not an
absence conclusion. Shared resolver owns boundary. Portable holder-get has no
episode flag; inherited claims remain visible. Do not universalize Claude's
transient-signal facts into other harness policy without manifest/source evidence.

Measured clean declared-wait exit immediately qualifies pending mail's same
native identity resume, including orphan open call; newer activity supersedes.
A stale recipient whose surface declares no message_idle route uses
message_stopped through the existing waiting wake mode, even if its recorded
turn posture is running. Active calls, version floors and operator-only
surfaces retain their declared wake rules.
Manual wake preserves other pending messages, including stale queued wakes.
Cancelled envelopes no longer reserve an idempotency key; a repeated intent
creates a fresh message while preserving the cancelled history. Deployment
QA reports name cancelled notices until a newer wake replaces them.
Refused/exhausted wake retains original pending receipt and sends covering-seat
diagnostic. outcome_unknown/skip notice waits for next completed target call
without acknowledgement; live call defers, acknowledgement suppresses.
surface_wake_operator_driven intentionally waits for user hook and alone emits
no failure notice. No recurring failure-notice recursion.

## Cross-references

Runtime overlap in Conduct/Implement routes to Refine; only authoring-phase
agents and the Dash work holder at survey/isolation attest coordination edges. [Lanes and claims](lanes-and-claims.md) owns
direction/owner/path policy; main-agent claims topic owns live schema.
Registered `yoke <subcommand>` is canonical; nonprod local Postgres dispatches
engine in-process. Runtime API imports/curl function server/direct clients are
operator-debug, never agent default. [Shell and CLI](shell-and-cli.md) owns lints,
authority and inline-short + command--help-deep recipes. Keep one copy-paste
operation recipe plus timely depth directive, not catalog restatements here.

## Related

- [Claude long commands and watcher waits](claude-long-commands.md)
