# Claude long commands and watcher waits

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Claude long commands
<!-- /yoke:breadcrumbs -->

Read this home before running long commands in a Claude main session or subagent; choose the declared wait surface and retain its capture through completion.

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

## Related

- [Claude session rules — the deep home](claude-sessions.md)
