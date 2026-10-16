# Exploratory QA Missions

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Exploratory missions
<!-- /yoke:breadcrumbs -->

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
| case config | `{"executor":"informed_subagent"}` |

Capability declarations are provisioning authority, and the two kinds above
resolve differently. <!-- qa:test-machine-capability -->`test-machine` is a project registration: materialization
resolves it against the project capability rows, and admission refuses a
mission whose project has registered no Test Machine. `browser-control` needs no project
capability row, because this method's own runner is declared to supply it on
the host the mission walks: admission admits the mission, and the walker
uses the managed browser for named identities or when the walk installed Yoke;
otherwise it drives the host browser, as the dispatch contract below describes.
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
  "method_config": {"executor": "informed_subagent", "machine": "macos-example"},
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

Use `informed_subagent` for each case. It isolates the walk and supplies the
relevant project and Progress Log context on the controller. Drive the target
with the printed host commands; a fresh target needs no Yoke or source checkout.
Do not add a checkout or project internals to bypass missing installed guidance.
The harness adapter must permit the mission's host, browser and artifact writes.
Cursor renders `readonly: false`; a stale adapter refuses as
`cursor_qa_walker_readonly` and names the rerender recovery.
Unsupported executors refuse as `agent_mission_executor_invalid`: update the
saved case to `informed_subagent` and rematerialize affected requirements.

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
- dispatching each case's informed subagent walker;
- combining walker returns into the primary written report;
- choosing and submitting the final verdict for every bundled case.

The walker never issues the verdict. Its turn returns one status:

- `WALK_STATUS: COMPLETE` — the walk reached a natural stopping point;
- `WALK_STATUS: HOST_WAIT` — submit only `host_wait` through the current bundle; [host turns](deployment-plan-execution.md#shared-host-turns-and-starting-state) owns queue/resume authority;
- `WALK_STATUS: HUMAN_GATE` — a person must act before it can continue;
- `WALK_STATUS: UNDETERMINED` — an essential fact could not be established for
  a reason other than a pending human action.

## Human-Gate Handoff

The walker returns `WALK_STATUS: HUMAN_GATE` with the action, why, observed
state, and resume point, then stops. It never sends Fleet mail. The parent
records that on the Progress Log and reads this run for host, browser
substrate, project profile, URL, and access route — not a Test Machine list.
Managed sign-in is `yoke browser authorize --identity NAME` on that host;
setup only starts the runtime. A host-native browser uses its declared access
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

## Related

- [Exploratory access and evidence](exploration-evidence.md)
- [Requirement state](requirement-state.md)
