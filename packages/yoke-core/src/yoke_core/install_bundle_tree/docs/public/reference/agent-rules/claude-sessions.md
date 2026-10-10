# Claude session rules — the deep home

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
Refused/exhausted wake retains original pending receipt and sends covering-seat
diagnostic. outcome_unknown/skip notice waits for next completed target call
without acknowledgement; live call defers, acknowledgement suppresses.
surface_wake_operator_driven intentionally waits for user hook and alone emits
no failure notice. No recurring failure-notice recursion.

## Long commands — the tier router

Apply only your tier; read only its prescriptive subsection:

- Main session running skills inline: ask watcher --print-streaming-pair; run
  printed mode-selected foreground or background/subscription command.
- Dispatched Agent subagent: foreground in one Bash call through completion.
- Uncertain tier: subagent; YOKE_HOOK_AGENT_TYPE identifies dispatched context.

### Main-session long commands

--print-streaming-pair is side-effect free: it runs no child/mutation/record.
Run what it prints. wait_mode=background-wake requires verified native idle wake
and prints command/subscription pair; in-turn covers headless/no/unverified wake
and prints foreground. Unknown waits. Give in-turn watcher Bash
`timeout: 600000`; lint-headless-watcher-timeout enforces watcher-only bound,
not all Bash. If harness yields/backgrounds even after that, same child is still
alive: continue its output handle until exit; never launch beside it or end
turn while it is held. A headless command's turn is its whole life.

Only taught early interruption: local check expected about one minute exceeded
that bound → interrupt cleanly, retain incomplete capture, commit, continue CI.
Never interrupt CI watcher for tool-budget yield. PostToolUse completion invalidates
earlier Stop evidence; no optimistic done from an open handle.

Monitor resumes current turn. Stop after arming while work claim held is denied,
including launched CLI: continue same turn. To deliberately go quiet, park first
(`yoke sessions touch --mode parked`); parked Stop escapes without reinjection,
next own tool clears park. Parallel useful work can accompany wait.

### Watcher inventory

Each wrapper captures/classifies output and owns exit/sentinel. Ask its
--print-streaming-pair before run; canonical flag precedes subcommand/separator.

| Wrapper recipe | Contract |
|---|---|
| yoke watch pytest --impacted main --bounded | Default change-scoped, bounded subset; full coverage belongs to final native QA. |
| yoke watch pytest -- {TEST_ARGS} | Bare pytest args, never nested python -m pytest. Project verification owns full anchors; bad partial anchors refuse. Injects -n auto; explicit -n N wins, rare order debugging -n 0. |
| yoke watch merge merge-item -- PREFIX-N | Also done-transition/merge-worktree; actionable terminal error/final result only, banners/polls/warnings raw, exit status/capture in sentinel. Standalone merge boundary is yoke merge item. |
| yoke watch deploy -- RUN-ID | Terminal errors/final outcome; stages/workflow polls/retry/no-progress raw. Authenticated HTTPS normally; replacing serving API requires operator authority. Same authority as run execute. |
| yoke watch fleet -- --project P | Repeat --project for scopes. Urgent worker mail/new work/red/block/abnormal/idle alarms wake; healthy churn/clears ride later urgent/changed report. Whole delimited compact report is one wake; due quiet reports still checked. Default 8h, duration 0 until interrupted; every exit gives exact fresh streaming-pair command. |
| yoke watch preflight -- --project P ENV | Migration model fleet of named registered environment, optionally --model/--checkout/db filters; source default, --engine-wheel pins built wheel. --record-receipt writes that fleet environment proof, --receipt-env chooses recorder; one env never covers another. Streams artifact/roster/progress/each verdict/total/receipt/failure, unbuffered preserved exit. |
| yoke watch qa-case -- --requirement-id N | Single native case verdict/envelope/failures/degraded relay, local pytest classified. CI poll states only on transition; quiet healthy gate has no-progress diagnostic, dead gate sentinel. |
| yoke watch qa-plan -- --item PREFIX-N --transition T | Or --deployment-run-id RUN --stage STAGE --member PREFIX-N --project P. Full plan/stage credit; single qa-case never credits a stage. |
| yoke watch ci-run -- REF | Existing exact-commit run conclusion; no fresh suite or manual GitHub loop. |
| yoke watch doctor -- --quick | Exactly one quick/full/only scope; project/fix/file optional. Only doctor shape: transport routes control plane/source checks, streams every verdict. Exit 0 clean, 1 FAIL/run failure, 2 missing scope. Source-only engine refuses relayed direct DB authority. |
| yoke watch tail PROGRESS_CAPTURE | Subscription to another wrapper, exits sentinel, resumes delivered cursor rather than replaying; only live watcher capture follower. |

CI-declaring projects route pytest remotely: commit first; base checkout or dirty
tree refuses. Wrapper publishes lane commit/merge base, adopts conclusion.
Remote exits: 0 pass, 1 fail, 2 pre-dispatch refusal, 3 timeout, 4 unreachable/
dispatch refusal, 5 cancelled. Drops machine-specific -n/numprocesses/rootdir.
--local or YOKE_PYTEST_LOCAL=1 is only short targeted/order/machine/CI-unreachable
check; dirty tree never justifies long local sweep. Local worker budget waits
and names holder. Unbounded triggers (non-Python/tooling/≥80% reachability over
≥100 known files; fixture and function-id edges preserved) report computable
subset/reason and defer remaining full native QA. --bounded is a no-op;
--widen is full local CI-outage fallback only. Files count paths; items count
collected tests, unknown totals labelled; end summary repeats counts.

Printed examples:

```bash
yoke watch merge --print-streaming-pair merge-worktree -- PREFIX-N
yoke watch pytest --print-streaming-pair --impacted main --bounded
yoke watch doctor --print-streaming-pair -- --quick
yoke watch qa-case --print-streaming-pair -- --requirement-id {REQUIREMENT_ID}
```

Background mode prints raw+filtered command, watch-tail subscription and
post-completion tail -80 inspection. In-turn prints foreground plus inspection,
preserves child exit and expects no later notice. Watcher captures are minted
under machine temp root via project_scratch_dir.mint_watcher_capture_pair;
operator --raw-capture may pin an explicit path.

### No-wrapper fallback

First check inventory, including merge subcommands and module-only watch_advance/
watch_lifecycle. Existing wrapper is preferred. For a truly uncovered long
command, capture full output to OS temp, stream progress AND failure signatures,
then inspect on completion. Manual pair has no sentinel; Monitor does not
self-terminate. File discovered wrapper gap through existing Yoke work/field-note
surface; eventual wrapper mints machine-rebound capture pair.

```bash
_raw_capture=$(mktemp -t yoke-cmd.XXXXXX)
{COMMAND} > "$_raw_capture" 2>&1
tail -f "$_raw_capture" | grep --line-buffered -E "FAILED|ERROR|Error|step|stage|progress|%\\]|====.*passed|====.*failed"
```

Tune classifier for actual command's progress and crashes. Monitor is installed
main-session allowlisted; never apply fallback backgrounding to subagents.
Run `python3 -m yoke_core.tools.watch_inventory check` before new long-command
teaching; it rejects preferred manual recipes where wrappers exist.

## Subagent long commands (foreground only)

Dispatched turns are atomic: SubagentStop ends that turn, returning agentId for
explicit parent continuation. Monitor wakes only current turn; self-armed
background + return loses progress and leaks waiters. Run matching watcher
foreground in one Bash call, read outcome/raw capture before returning. Parent
may drive Monitor events consumed by current subagent call; subagent never
self-arms background pair. Tighter parent dispatches, not bigger self-background
budgets, handle insufficient turn capacity.

lint_subagent_background denies background Bash/Monitor/ScheduleWakeup/TaskOutput/
background watcher in dispatched context (YOKE_HOOK_AGENT_TYPE, secondary
agent-type). Main default allowance does not authorize subagent exception.
Project lint config default deny; no-subagent-background-check is audit-only.
Renderer puts role env on all four background-tool hook matchers from universal
HOOK_ORDERING, so new guards propagate without per-adapter copies.

One armed subscription is background progress; original call is in-turn waiter.
No duplicate Monitor, same-capture loop, background waiter, bare watcher tail-f/F
or short sleep-and-tail. Use minted watch tail; completion notice only after
reported background-wake. One completed raw tail -80 is fine. Truly unwrapped
fallback cadence: 60s → 90s → 120s → max~300s, never faster than 60s.
lint_monitor_watcher_tail/lint_long_command_polling own configured modes.

### Suppression tokens

Tokens are audit evidence, never independent authority to violate project rules:
`# lint:no-main-check`, `# lint:no-lifecycle-mutation-check` and
`# lint:no-polling-check` name specific guards.
`# lint:no-monitor-watcher-tail-check`, `# lint:no-raw-pytest-check` and
`# lint:no-subagent-background-check` are audit-only and do NOT unblock; use minted
subscription/admitted pytest/foreground respectively. Full operation refusal
and --help own sanctioned recovery. Do not blanket-suppress unrelated checks.

### Monitor output and messaging

Relay matched line/digest verbatim into own visible output, including suppressed
N ticks suffix. One digest is one wake; do not unpack into separate turns.
Merge/deploy suppress routine progress/retry/metadata/no-progress; other wrappers
may batch progress (flush-seconds where supported). Silence needs no filler.
This never authorizes Fleet mail: no percentages/elapsed polls/heartbeats/still
green upward. End sends no mail. Deliberate yoke say --steering is for actionable
red gate/blocker/instruction conflict/out-of-scope defect/decision/terminal state.
Steering has its own fleet liveness watcher. Messaging rule is coordination,
not invented send-path refusal.

PreToolUse Monitor adds passive relay context from hint_monitor_relay DEFAULT_REMINDER
or monitor_relay_hint_text setting; `python3 -m yoke_core.domain.hint_monitor_relay
--help` owns depth. Scope follows manifest idle-wake capability; do not infer a
Monitor primitive for another harness. It does not change operator behavior.

## Cross-references

Runtime overlap in Conduct/Implement routes to Refine; only authoring-phase
agents attest coordination edges. [Lanes and claims](lanes-and-claims.md) owns
direction/owner/path policy; main-agent claims topic owns live schema.
Registered `yoke <subcommand>` is canonical; nonprod local Postgres dispatches
engine in-process. Runtime API imports/curl function server/direct clients are
operator-debug, never agent default. [Code and CLI](code-and-cli.md) owns lints,
authority and inline-short + command--help-deep recipes. Keep one copy-paste
operation recipe plus timely depth directive, not catalog restatements here.
