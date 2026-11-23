# Exploratory QA Missions

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Exploratory missions
<!-- /yoke:breadcrumbs -->

An exploratory mission states territory and a good outcome; its walker chooses
the sequence at runtime. Use `exploratory-mission` for discovery and judgment;
use Command, Browser check or Machine check for deterministic assertions.

## Contract

The exploratory QA method has these immutable properties:

| Field | Value |
|---|---|
| `runner_id` | `agent_mission` |
| `verdict_path` | `agent` |
| `concurrency_mode` | `serial` |
| required capabilities | `browser-control` |
| case config | `{"executor":"informed_subagent"}` |

A mission without a declared host explores on the controller, the machine
running the main session. It records a mission docket without a lease and
reaches `awaiting_walk_review` without a restore artifact or reset debt.
It ignores a run's `--test-machine` pin. Declare `method_config.os` to use a
Test Machine of that type; that host mission requires starting
state and retains the lease/reset/restore protocol described below.
The runner supplies `browser-control` without a project capability row.
Controller walkers use local tools and browsers. Host walkers use managed
browsers for named identities or when the walk installed Yoke; otherwise the
host browser. Host access comes from the `QA_HOST:` lease recorded on
`qa_plan_executions.test_machine_lease_id`, never an undeclared access path.
A walk that belongs to a deployment run opens its prompt with that run's ID,
environment and full commit, labelled "deployment run" apart from the
capture `--run-id` its commands use.

## Authoring Shape

Write territory and an observable outcome. Split platform coverage by OS
and use required capability tags for portable missions. Order a small
cross-machine mission after single-host missions and declare its host set.

Ask only for actions a real user takes; browser actions must come from the
[action reference](browser-scenarios.md#action-reference), with the full list in
`yoke qa browser step --help`. Set up unusual states with fixtures, seeded
identities or component tests; do not ask walkers to edit DOM text, override
responses or measure element widths. Keyboard proof needs a declared Test
Machine with the required input support. For phone checks, use a phone-sized
viewport or the iOS Simulator on a macOS host; there is no phone Test Machine,
and a viewport check does not prove real-phone touch behavior.

```json
{
  "case_key": "new-user-installation",
  "method_id": "exploratory-mission",
  "instructions": "Install as a new user, work through onboarding, and investigate confusing, broken, missing, or unsafe behavior using the terminal, browser, and visible desktop.",
  "expected_outcome": "Return a ranked actionable report, name what could not be verified and why, and return a precise handoff if a person must act.",
  "method_config": {"executor": "informed_subagent", "os": "macos"},
  "host_baselines": ["fresh-host"]
}
```

Set `method_config.os` and any required `capability_tags` so a host mission
can use any verified, healthy match. If all matches are busy, QA takes the
shortest eligible host line. Test Machines of one kind are identical, so a
case never names a host; authoring refuses one with `test_machine_name_forbidden`.
`yoke qa plan run --test-machine NAME` picks a host for that run only.
See [Machine QA host selection](test-machine-desktop.md) for platform
inference and refusal recovery.

For a mission that needs two hosts at once, list OS slots instead of `os`:
`"test_machines":[{"os":"linux"},{"os":"macos","driver":true}]`. Name at least
two slots and exactly one `driver`, the host the walker drives. Set
`capability_tags` as an object from slot OS to tags, such as
`{"macos":["macos:15"]}`; the tags apply to every slot of that OS, and a list
is refused with `test_machine_set_invalid`. Platform words in instructions do not
constrain the host set. The plan runner queues each slot at the execution's one
queue place and admits the set only when every slot has a free, verified,
healthy host, giving each slot a distinct one in a single step; otherwise
nothing is acquired and every slot keeps its place. Both leases remain
held and heartbeated through the walk and independent review. Mission access
refuses if either lease has been lost; completion or abort releases both.

Every machine-run case declares the state it starts from, and authoring and
materialization refuse one that does not. A host mission names `host_baselines`
(`fresh-host` or `shell-preconfigured`). Browser identity verification on the
host requires `shell-preconfigured`. Fresh-host walks skip automatic browser
identity selection. A mission may `inherit` from
its machine-run predecessor on the same driver as the chain's tail. The runner
isolates that chain and holds its host union before preparation, so no later
capture disturbs the inherited state. Nothing may inherit after a mission.
Standalone execution needs the chain in its own plan; see
[Machine partitions](deployment-plan-execution.md#machine-partitions).
Baseline cleanup preserves live scratch and requires 1 GiB free before mission staging; [temporary-state and disk recovery](test-machine-desktop.md) names receipts and live-lease refusals. A mission that can only be judged after real production traffic, such as a real failed wake that a relay then claimed, sets `wake_path: manual` with a one-line `wake_evidence`; its owner is woken to confirm that evidence before running it ([cases that wait for real traffic](standalone-plans.md#cases-that-wait-for-real-traffic)).

Do not turn likely landmarks into steps. The worked Machine QA case
`installer-exploration` deliberately replaces the territory of the
installer campaign with one agent-chosen mission.

The campaign combines deterministic checks and missions in one environment-neutral template. Generation
fills its application and installer addresses, release channel, and display name
from the plan's bound environment through `{{app_url}}`, `{{installer_base_url}}`,
`{{release_channel}}`, and `{{environment_display_name}}`. Each plan tests one environment;
testing another requires a separate plan bound to it, using the same template.

Use `informed_subagent` for each case. It isolates the walk and supplies the
relevant project and Progress Log context on the controller. For a host mission, drive the target
with the printed host commands; a fresh target needs no Yoke or source checkout.
Do not add a checkout or project internals to bypass missing installed guidance.
Walkers inherit the parent session tools and permissions on every harness.
Their role instructions permit mission host, browser and artifact writes while
forbidding repository edits.
Unsupported executors refuse as `agent_mission_executor_invalid`: update the
saved case to `informed_subagent` and rematerialize affected requirements.

## Stage fixtures

A mission that needs a disposable stage project keeps its execution and
artifacts on production and runs fixture claim, merge and cancel steps from a
child harness started in the fixture checkout with `YOKE_ENV=<stage
connection>`. That child's own opening hook registers it on stage; the walker
never reuses the production session or registers one by hand. Controller
version matching follows [Candidate controller](candidate-controller.md). Two
known defects surface as findings, not routine steps: a fixture seed
publication refusal recoverable only by a hand `git push origin main`, and a PR
gate still requiring `test_results` after a passing Command capture.

## Cleanup

A mission cleans up everything it creates, such as repositories, accounts and
records the product registered, using the product's own commands, and reports
anything it could not remove. A host mission's walk-end removes only its staging and
restores the Test Machine; it never removes what the walk created elsewhere.

Host cleanup, such as uninstalling a checkout on the Test Machine, needs the
mission's lease and runs through `yoke qa mission host-command`. Server
cleanup, such as `yoke --env ENV projects retire`, `yoke --env ENV machine
retire` and deleting fixture repositories, needs no lease. An aborted host walk keeps its lease
until walk-end, so it finishes both; if access is gone anyway, the walker still
does the server cleanup the refusal names.

Create every mission-owned GitHub fixture repository as private, using
`gh repo create OWNER/NAME --private`, including a repository created from
cloned public history. Record each exact `OWNER/NAME` when created, including a
repository the product creates during the mission, and delete each with
`gh repo delete OWNER/NAME --yes` before walk-end. Never delete an upstream or
pre-existing repository, and never hand cleanup to steering. When a removal is
refused, record the refusal and its recovery and list everything still present
in the walker report and the main agent's final verdict. Do not report that
cleanup is complete.

## Execution and Review

Run just one materialized mission without starting its sibling requirements:

```text
yoke qa case run --requirement-id N
```

This creates a one-requirement plan execution using the same controller or host walk,
review bundle and main-agent verdict path below, including deployment-member
missions. Exit code `12` carries the typed review continuation. Repeating the
case command reprints pending review without recapturing. An `inherit` mission
cannot run alone because its predecessor must capture in the same execution;
run the ordered plan instead. A case already owned by a standalone execution
resumes through that execution rather than creating another one.

Run the attached plan at its transition:

```text
yoke qa plan run --item PREFIX-N --transition <transition> \
  --test-machine <registered-name>
```

The run pin is optional and must agree with every case-authored constraint.
Without one, admission prefers a verified free machine and reports its reason.

The plan runner reaches the declared host baseline, records a zero-artifact
mission docket, advances the full roster, creates the existing review bundle,
and enters `walking` until every mission records walk-end. Exit code `12` means the
typed review continuation must run now. It is not itself a human-review state,
and it is not a pass: the result carries `review_status="pending"` and no QA
verdict exists until the reviewer submits the bundle.

For deployment item-scoped QA, reaching `walking` automatically
wakes the capturing session through the item-QA notice path with the exact
`yoke watch qa-plan` re-entry command. It resumes the pending bundle without
recapturing. A gone owner routes to steering for normal idle/gone-holder
restaffing. The review notice has its own execution key; the earlier stage
wait notice cannot suppress it.

While parked, the execution retains and heartbeats its Test Machine lease. The
returned dispatch has `dispatch_kind=main_agent_mission`. The main agent owns:

- the item, work claim, Progress Log, and the human-request route;
- starting a fresh walker per chunk: one source case or a small same-host group,
  with `walker_dispatches[].prompt` unchanged plus a compact handoff of host
  state, held windows, proven facts and evidence ids; never resume a large
  walker history;
- combining walker returns into the primary written report;
- retaining leases and choosing/submitting each bundled case's final verdict.

On Codex, `spawn_agent` can refuse with `collab spawn failed: agent thread
limit reached` while an earlier walker still holds its thread, and no tool
closes that thread. Wait for the running walker to return, then spawn the fresh
walker. If the spawn still refuses, walk the remaining chunk yourself with
foreground calls under the walker rules below, and note the refusal in the
primary report. Do not raise Codex thread limits or edit Codex config.

Walkers run host-command calls foreground with tool yield at or above the
call timeout (`yield_time_ms` uses milliseconds), never short-yield polling.
They return one status, never a verdict:

- `WALK_STATUS: COMPLETE` — the walk reached a natural stopping point;
- `WALK_STATUS: HOST_WAIT` — submit only `host_wait` through the current bundle; [host turns](deployment-plan-execution.md#shared-host-turns-and-starting-state) owns queue/resume authority;
- `WALK_STATUS: HUMAN_GATE` — a person must act before it can continue;
- `WALK_STATUS: UNDETERMINED` — an essential fact could not be established for
  a reason other than a pending human action.

## Human-Gate Handoff

The walker does every step an agent physically can: it drives the leased
GUI/desktop session (opening harnesses, choosing permission modes, typing codes
into wizards), approves machine-connect and device codes in the host's already
signed-in browser, and follows approval links. It answers consent prompts, selects
the declared identity's email in Google's chooser and dismisses stray sheets.
It records every workaround with evidence in the existing ranked findings.
A workaround must preserve the tested behavior: CLI machine approval cannot
replace browser approval when that is the assertion. The reviewer must not pass
a case whose workaround touched the behavior under test; rerun it preserving
that boundary. Real password, 2FA and payment steps are human gates.
There it returns `WALK_STATUS: HUMAN_GATE` naming exactly that one entry, why,
observed state, and resume point, then stops. It never sends Fleet mail. The parent
records that on the Progress Log and reads this run for host, browser
substrate, project profile, URL, and access route — not a Test Machine list.
Managed sign-in is `yoke browser authorize --identity NAME` on that host;
setup only starts the runtime. A host-native browser uses its declared access
surface. Preview `yoke say --preview --steering`: `delivered` means a live
covering seat, so send `--steering` and read the receipt. `awaiting_seat` is
not delivery — cancel it, then `yoke say --preview --actor` and `--actor` for
the human owner: `yoke items get PREFIX-N owner` prints `NAME (actor id: N)`.
An `unassigned`, `unknown actor`, nonhuman, or refused owner is a named recovery. `--item` returns the answer to the holder. Acknowledgement
is not proof. Dispatch a fresh walker, continuing when the held host must keep its state.
Prepare the required session during the walk or in a preceding case in the
same chain. Ask for password entry while holding the host lease. The
[starting-state contract](case-attachment-rules.md#machine-case-starting-state)
describes how an inherited case can verify prepared files.

## Holding a Walk, and Continuing a Settled One

A held walk keeps its place while its owning session has not ended, whatever
the session's mode or heartbeat age. A walk is held while it is queued in
`waiting` or finished and in `awaiting_walk_review`; nothing heartbeats either
state. Only the owner's recorded session end makes one abandoned; the sweep
settles it with the existing `stale-heartbeat` reason.

For `active` and `walking` executions, inactivity starts at the latest walk
heartbeat or tool call by the owner or one of its subagents. At 20 silent
minutes the sweep mails the live, unparked owner once per silence, naming the execution, item, Test
Machine, abort time and fix: run the next step through `yoke qa mission host-command`,
which heartbeats the walk, or cancel it with `yoke qa plan abort` (holder release
refuses `qa_execution_holds_lease`). `yoke watch fleet` prints it as `stale-walk`.
A walker told to hold can park (`yoke sessions touch --mode parked --reason "..."`); a live parked owner
protects its active walk from the stale sweep. An ended owner provides no
such protection. Terminal settlement stamps an unreviewed capture with an
`error` verdict.

That verdict records the execution, not a judgment on the walk, and the Test
Machine still holds every bit of state the walk built. The way back in is a
continuation:

```text
yoke qa plan run --resume-execution-id EXECUTION_ID --continue-mission
```

Host-wait and continuation commands omit `--test-machine`. Simultaneous cases keep
their declared driver and full host set. For single-host cases, the scheduler
recovers each platform's original host from the execution's recorded leases and runs,
including its continuation source. A platform not used before selects a fresh
eligible host; a global pin cannot represent a roster using several hosts.
A replacement starts fresh from its own OS, tags or OS slots.

A continuation records new runs over the same roster without resetting hosts.
Its latest runs supersede the swept `error`; the prior runs retain their
`stale-heartbeat` history.

The flag is refused unless the named execution is the latest eligible source, is terminal,
ended with `release_reason` `stale-heartbeat`, ran at least one
`agent_mission` case, and runs no `host_control` case whose own host baseline
would reset the very host a continuation inherits. Each refusal names the
condition that failed and the command that does apply. `yoke qa mission
host-command` refuses a settled execution with that exact continuation command
rather than a bare state mismatch, so a resuming walker is never left to guess
— and must never start an ordinary plan run to get back in when its case
declares a baseline, because that resets the host.

## Related

- [Exploratory access and evidence](exploration-evidence.md)
- [Requirement state](requirement-state.md)

Mission preparation enters `walking`; the last mission’s recorded walk-end
changes it to `awaiting_walk_review`. Ordinary captures enter review directly.
Both retain their existing verdict and host-custody rules.
