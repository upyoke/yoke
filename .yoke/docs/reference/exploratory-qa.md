# Exploratory QA Missions

An exploratory mission is one materialized QA case whose sequence is chosen by
an agent at execution time. The case states the territory and good outcome in
prose. It does not script the intermediate commands, browser actions, desktop
interactions, or investigation branches.

Use the `exploratory-mission` method when discovery and cross-substrate judgment
are the point. Use a Command, Browser check, or Machine check when the expected
sequence and assertions are deterministic; those methods are faster, cheaper,
and repeatable.

## Contract

The Machine QA Pack method has these immutable properties:

| Field | Value |
|---|---|
| `runner_id` | `agent_mission` |
| `verdict_path` | `agent` |
| `concurrency_mode` | `serial` |
| required capabilities | `browser-control`, <!-- qa:test-machine-capability -->`test-machine` |
| case config | `{"executor":"informed_subagent"}` or `{"executor":"naive_target_session"}` |

Capability declarations are provisioning authority, and the two kinds above
resolve differently. <!-- qa:test-machine-capability -->`test-machine` is a project registration: materialization
resolves it against the project capability rows, and admission refuses a
mission whose project has registered no Test Machine. `browser-control` needs no project
capability row, because this method's own runner is declared to supply it on
the host the mission walks: admission admits the mission, and the walker
drives the host's own browser, or the Yoke browser runtime when the walk
installed Yoke there, as the dispatch contract below describes.
The Test Machine connection comes from the `QA_HOST:` coordination lease
recorded on `qa_plan_executions.machine_lease_id`; the mission does not open
an undeclared host or browser path.

## Authoring Shape

Write one case with broad instructions and an observable good outcome:

```json
{
  "case_key": "new-user-installation",
  "method_id": "exploratory-mission",
  "instructions": "Install as a new user, work through onboarding, and investigate confusing, broken, missing, or unsafe behavior using the terminal, browser, and visible desktop.",
  "expected_outcome": "Return a ranked actionable report, name what could not be verified and why, and return a precise handoff if a person must act.",
  "method_config": {"executor": "naive_target_session", "machine": "macos-example"},
  "host_baselines": ["fresh-host"]
}
```

Omit `machine` when any registered host can run the mission. When present, it
is validated during plan authoring and becomes the case's durable
<!-- qa:test-machine-capability -->`test-machine:<name>` capability constraint. Execution also reads the pin from
`method_config` for direct requirements and their admitted deployment copies;
omitting `--machine` preserves that pin, and a conflicting run pin is refused.

For a mission that needs two hosts at once, also declare
`"machines":["linux-example","macos-example"]` with `"machine":"macos-example"` naming the
driving host. Every name must be registered and listed once. The plan runner
acquires the complete set in sorted name order through each host's FIFO;
contention releases partial acquisitions before waiting. Both leases remain
held and heartbeated through the walk and independent review. Mission access
refuses if either lease has been lost; completion or abort releases both.

Every machine-run case declares the state it starts from, and authoring and
materialization refuse one that does not. A mission names `host_baselines`
(`fresh-host` or `shell-preconfigured`), or sets `"starting_state":"as_is"`
with a `starting_state_reason` to walk the machine as found — that mission must
also tell its walker to leave the home untouched. A mission cannot `inherit`: it is walked after the plan's other cases, so no case runs right before it.
Baseline cleanup preserves live scratch and requires 1 GiB free before mission staging; [temporary-state and disk recovery](test-machine-desktop.md) names receipts and live-lease refusals.

Do not turn likely landmarks into steps. The worked Machine QA Pack case
`installer-exploration` deliberately replaces the territory of the ten-case
scripted installer campaign with one agent-chosen mission.

The scripted campaign uses one environment-neutral source template. Generation
fills its application and installer addresses, release channel, and display name
from the plan's bound environment through `{{app_url}}`, `{{installer_base_url}}`,
`{{release_channel}}`, and `{{environment_display_name}}`. Each plan tests one environment;
testing another requires a separate plan bound to it, using the same template.

Choose the executor per case:

- `informed_subagent` isolates the walk while supplying the relevant project
  and Progress Log context. Its harness adapter must permit the mission's
  state-changing host, browser, and artifact operations. Cursor renders this
  contract explicitly as `readonly: false`; dispatch refuses
  `cursor_qa_walker_readonly` before starting a walker when the discovered
  adapter is stale, and tells the caller to rerender before retrying.
- `naive_target_session` starts a separate agent session on the target machine.
  A fresh machine without a project checkout is naive by construction. Do not
  add a checkout or project internals to make the walk easier.

## Execution and Review

Run the attached plan at its transition:

```text
yoke qa plan run --item PREFIX-N --transition <transition> \
  --machine <registered-name>
```

The run pin is optional and must agree with every case-authored constraint.
Without one, admission prefers a verified free machine and reports its reason.

The plan runner reaches the declared host baseline, records a zero-artifact
mission docket, advances the full roster, creates the existing review bundle,
and parks the execution in `awaiting_agent_review`. Exit code `12` means the
typed review continuation must run now. It is not itself a human-review state,
and it is not a pass: the result carries `review_status="pending"` and no QA
verdict exists until the reviewer submits the bundle.

For deployment item-scoped QA, reaching `awaiting_agent_review` automatically
wakes the capturing session through the item-QA notice path with the exact
`yoke watch qa-plan` re-entry command. It resumes the pending bundle without
recapturing. A gone owner routes to steering for normal idle/gone-holder
restaffing. The review notice has its own execution key; the earlier stage
wait notice cannot suppress it.

While parked, the execution retains and heartbeats its Test Machine lease. The
returned dispatch has `dispatch_kind=main_agent_mission`. The main agent owns:

- the item, work claim, Progress Log, and the human-request route;
- dispatching each case's walker according to its executor;
- combining walker returns into the primary written report;
- choosing and submitting the final verdict for every bundled case.

The walker never issues the verdict. Its turn returns one status:

- `WALK_STATUS: COMPLETE` — the walk reached a natural stopping point;
- `WALK_STATUS: HOST_WAIT` — submit only `host_wait` through the current bundle; [host turns](qa-platform/case-attachment.md#shared-host-turns-and-starting-state) owns queue/resume authority;
- `WALK_STATUS: HUMAN_GATE` — a person must act before it can continue;
- `WALK_STATUS: UNDETERMINED` — an essential fact could not be established for
  a reason other than a pending human action.

## Human-Gate Handoff

The walker returns `WALK_STATUS: HUMAN_GATE` with the action, why, observed
state, and resume point, then stops. It never sends Fleet mail. The parent
records that on the Progress Log and reads this run for host, browser
substrate, project profile, URL, and access route — not a Test Machine list.
Managed sign-in is `yoke browser authorize` on that host and profile; setup
only starts the runtime. A host-native browser uses its declared access
surface. Preview `yoke say --preview --steering`: `delivered` means a live
covering seat, so send `--steering` and read the receipt. `awaiting_seat` is
not delivery — cancel it, then `yoke say --preview --actor` and `--actor` for
the numeric human `items.owner`. A non-numeric, nonhuman, or refused owner is
a named recovery. `--item` returns the answer to the holder. Acknowledgement
is not proof. Dispatch a fresh walker, continuing when the held host must
keep its state.

## Holding a Walk, and Continuing a Settled One

A walker told to hold is parked (`yoke sessions touch --mode parked --reason
"..."`), and a parked session stops heartbeating its execution. That silence is
a declared wait, not an absence, so a live parked owner's execution is exempt
from the stale sweep below and keeps its mission. The exemption lasts exactly
as long as the session: if the park outlives it — a sleep, a reload, an
explicit end — the sweep settles the execution and terminal settlement stamps
its unreviewed capture with an `error` verdict.

That verdict records the execution, not a judgment on the walk, and the Test
Machine still holds every bit of state the walk built. The way back in is a
continuation:

```text
yoke qa plan run --item PREFIX-N --transition T --continue-mission
```

A continuation is an ordinary new execution over the same roster, recording
its own runs, with one difference: it reaches no host baseline, so the host
keeps the state the settled walk built. Because the projections that paint a
QA failure read a requirement's latest run, the continuation's own run
supersedes the swept `error` without rewriting it — the prior run stays as
history with its `stale-heartbeat` reason.

The flag is refused unless the subject's most recent execution is terminal,
ended with `release_reason` `stale-heartbeat`, ran at least one
`agent_mission` case, and runs no `host_control` case whose own host baseline
would reset the very host a continuation inherits. Each refusal names the
condition that failed and the command that does apply. `yoke qa mission
host-command` refuses a settled execution with that exact continuation command
rather than a bare state mismatch, so a resuming walker is never left to guess
— and must never start an ordinary plan run to get back in when its case
declares a baseline, because that resets the host.

## Substrate Access

The review dispatch supplies an exact host command template:

```text
yoke --env <connection> qa mission host-command --item PREFIX-N \
  --execution-id <execution-id> --requirement-id <requirement-id> -- ARGV...
```

This command revalidates subject ownership, the parked execution, immutable
case snapshot, and retained lease before resolving client-local Test Machine
credentials. It accepts bounded argv rather than shell text and returns
redacted output. Every path in that argv names the **Test Machine's**
filesystem, never the calling machine's, so the session-cwd write-authority
guard exempts it from local write classification — a shell redirect written
after the argv still runs locally and stays enforced.

Missions are walked one at a time, in bundle order, because they share the
plan's one Test Machine. The walker dispatch carries the scratch path and two
commands. `walk-start` runs before any other host command: it re-reaches the
baseline the docket proved, since later cases ran (never in a continuation),
restores declared OS packages and creates the `0700` scratch. `walk-end`:

```text
yoke --env <connection> qa mission walk-end --item PREFIX-N \
  --execution-id <execution-id> --requirement-id <requirement-id> --run-id <run>
```

Where the product reads a secret on stdin, pipe it and touch no disk at all.
Otherwise every file carrying a token or password is staged inside that
directory and nowhere else, never a loose `/tmp` path. `walk-end`
removes the directory with plain OS commands (no Yoke install on the host),
restores the declared starting state, and records that restore as a
`starting_state_restore` artifact on the mission's run; it exits non-zero
naming `mission_scratch_not_removed`, `starting_state_restore_failed` (with the
`yoke test-machine reset` recovery) or `starting_state_restore_unrecorded`.
`yoke qa plan review-submit` refuses with `mission_walk_unfinished` while any
mission's scratch is still on the host. Both delete a stale owner marker.

The lease holder owns every Yoke project it creates: it appends each slug to
the item's Progress Log as created, so a replacement can finish the cleanup,
and before returning retires each with its own control-plane CLI (`yoke
projects retire --project SLUG --reason ...`), never Yoke on the Test Machine.

On macOS, append `--gui-session` when a command needs the login keychain or
window server. Three apparently different failures share one diagnosis:

- screenshot capture cannot create an image from the display;
- switching to the audit session is not permitted;
- a keychain-backed CLI reports OAuth expired and unrefreshable while its
  credential file is unchanged and the console session works.

They mean the command ran in the wrong session. Retry through the Terminal
GUI-session bridge before diagnosing broken credentials or privacy settings.

Use the declared browser-control substrate for web interaction. Test Machines
start without Yoke. When the walk installed Yoke on the target, the dispatch's
lease-routed `yoke qa browser setup` materializes the packaged runtime and
`yoke qa browser step --base-url URL --step-json JSON` drives it one chosen
step at a time; no scenario is authored in advance. Otherwise the walker opens
the host's own browser (Safari on macOS; the desktop's default elsewhere) and
drives it by screenshots and keystrokes through the host command. It never
installs Yoke on a Test Machine to get a browser.

Agents complete setup and application steps that do not need the user.
The user supplies personal credentials. Password, MFA, passkey and personal
permission prompts return a human gate for this run's host, substrate, and resume state.
Prepare and restore saved browser profiles through the
Machine QA Pack per-OS procedures at `docs/packs/machine-qa/browser-profile-baseline.md` (installed by the Machine QA Pack).
The mission execution contract above governs every host command.

## Evidence Discipline

Perception is disposable. A walker may inspect hundreds of screens, DOM states,
or command outputs while deciding what to do; those observations are not
automatically evidence.

Attach only deliberate proof that makes a finding or human gate independently
understandable. The dispatch carries the single runtime-owned artifact limit,
and the shared artifact-add surface rejects attachments beyond it. Never make a
parallel run to evade the cap, and never attach credentials or secret-bearing
content.

A mission attaches evidence as bytes, never as a path on the test host. That
host's starting state is restored when the walk ends, so an artifact row
naming one of its paths outlives its own file: the row survives and the
evidence does not. The artifact-add surface refuses a mission handle this
control plane cannot read and names the byte-carrying recipe instead — the
walker's own `--content-file` when it walks on the target, or the bytes read
back through the remote command when it drives the target from elsewhere.

The ranked written report is the primary deliverable. Each finding should name
observed and expected behavior, impact, minimal reproduction, confidence, and
supporting artifact ids when present. The report must state every important
area that could not be verified and why.

## Verdict Submission

After all walker returns are incorporated, the main agent sends one complete
stdin batch through the exact `submit_command` in the dispatch:

```json
{"verdicts":[{"requirement_id":123,"verdict":"pass|fail|undetermined","rationale":"non-empty written report"}]}
```

Include exactly one row for every bundle case. `undetermined` is earned by the
artifacts already attached to that capture and requires a rationale naming what
remains undecidable. It halts the item until a project owner or operator records
the canonical evidence decision, so choosing it deliberately spends a human
interaction. If the case never ran or produced no artifact, record the failed
or `blocked_on_precondition` execution outcome instead; that asks no person and
returns failure to the scheduler. Do not map either condition to pass.

## Decision Disposition

An `undetermined` verdict raises a `qa_needs_review` decision request against
its requirement. That request exists because the walk could not determine a
verdict, so it belongs to the walk: when the plan execution reaches any
terminal state — completed, aborted, or error — every review it raised is
withdrawn in the same transaction, carrying the execution's state and its
`release_reason` onto the decision as the recorded reason. A requirement that
another live execution is still walking is retained; the subject-state
contract refuses to withdraw a decision whose subject has not ended.

Termination is guaranteed rather than hoped for. An execution whose owner has
stopped reporting progress is reaped into `aborted` with `release_reason`
`stale-heartbeat` after 30 minutes without a heartbeat — unless its owning
session is live and parked, which is a declared hold rather than an absence
(see *Holding a Walk, and Continuing a Settled One*). Reaping is
deliberately blind to row vintage: a stranded execution written before
executions carried an execution target still settles, because resolving that
target is a precondition for *running* an execution, not for abandoning one.
For the same reason abandoning a non-progressing execution is open to any
session on its subject — the session that owned a stranded execution is by
definition the one that is no longer there — while a live execution, or one
whose owner is parked and still holding it, keeps its owner-only guard.

That parked-owner exemption leaves one execution nobody can end. A member
parked on a release wait holds an item-level execution its own walk opened,
and when the run delivering that member scopes it a run-bound execution
instead, the run-bound one produces the evidence while the item-level row
stays live forever: the done gate reads any live item-level execution as
unsettled, so the member can never close. Release settlement resolves it
without touching the owner-only guard, because the only rows it takes are
ones that recorded nothing at all — cursor still at zero and no
`qa_plan_execution_results` row. Such a row carries no evidence, so aborting
it discards none; it ends with `release_reason`
`superseded-by-run-scoped-item-qa`. An execution that recorded any result
keeps blocking and keeps its owner. Terminalizing one of these blockers by
any route replays the settling run's settlement on that same event, so a
shared gate that already passed never waits on a hand re-drive.

Reaping and withdrawal run together whenever the Inbox is read, so a reader
never sees a blocking row that blocks nothing. Run the same convergence
deliberately, with a receipt naming what was reaped, withdrawn, and retained:

```text
yoke decision-requests dispose-ended [--project-id N ...] --json
```

The pass is kind-blind: it applies each kind's own subject-state contract, so
it also releases, for example, a strategy-revision review that a later
revision has superseded.
