# Exploratory QA Missions

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Exploratory missions
<!-- /yoke:breadcrumbs -->

An exploratory mission states territory and a good outcome; its walker chooses
the sequence at runtime. Use `exploratory-mission` for discovery and judgment;
use Command, Browser check or Machine check for deterministic assertions.

## Contract

The Machine QA Pack method has these immutable properties:

| Field | Value |
|---|---|
| `runner_id` | `agent_mission` |
| `verdict_path` | `agent` |
| `concurrency_mode` | `serial` |
| required capabilities | `browser-control`, <!-- qa:test-machine-capability -->`test-machine` |
| case config | `{"executor":"informed_subagent"}` |

<!-- qa:test-machine-capability -->`test-machine` resolves against project
registrations; admission refuses without one. The runner supplies
`browser-control` without a project capability row. Walkers use managed browsers
for named identities or when the walk installed Yoke; otherwise the host browser.
The connection comes from the `QA_HOST:` lease recorded on
`qa_plan_executions.machine_lease_id`, never an undeclared access path.

## Authoring Shape

Write territory and an observable outcome; split by machine so separate host
queues run in parallel. Order a small cross-machine mission after the
single-machine missions; declare its host set below.

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

Omit `machine` to select a registered host matching the case OS. Execution
checks the method, instructions, capabilities and executable steps before
leasing a host; portable cases keep verification/name ordering. An unavailable
platform refuses as `test_machine_platform_unavailable`: register and verify
a matching host, then retry with its `--machine NAME`. When present, it
is validated during plan authoring and becomes the case's durable
<!-- qa:test-machine-capability -->`test-machine:<name>` capability constraint. Execution also reads the pin from
`method_config` for direct requirements and their admitted deployment copies;
omitting `--machine` preserves that pin, and a conflicting run pin is refused.

For a mission that needs two hosts at once, also declare
`"machines":["linux-example","macos-example"]` with `"machine":"macos-example"` naming the
driving host. Every name must be registered and listed once. Each host uses its
registered OS; the inferred case platform must match at least one host in the
set. Platform words in instructions do not change the declared driver. The plan runner
acquires the complete set in sorted name order through each host's FIFO;
contention releases partial acquisitions before waiting. Both leases remain
held and heartbeated through the walk and independent review. Mission access
refuses if either lease has been lost; completion or abort releases both.

Every machine-run case declares the state it starts from, and authoring and
materialization refuse one that does not. A mission names `host_baselines`
(`fresh-host` or `shell-preconfigured`), or sets `"starting_state":"as_is"`
with a `starting_state_reason` to walk the machine as found — that mission must
also tell its walker to leave the home untouched. A mission may `inherit` from
its machine-run predecessor on the same driver as the chain's tail. The runner
isolates that chain and holds its host union before preparation, so no later
capture disturbs the inherited state. Nothing may inherit after a mission.
Standalone execution needs the chain in its own plan; see
[Machine partitions](deployment-plan-execution.md#machine-partitions).
Baseline cleanup preserves live scratch and requires 1 GiB free before mission staging; [temporary-state and disk recovery](test-machine-desktop.md) names receipts and live-lease refusals. A mission that can only be judged after real production traffic, such as a real failed wake that a relay then claimed, sets `wake_path: manual` with a one-line `wake_evidence`; its owner is woken to confirm that evidence before running it ([cases that wait for real traffic](standalone-plans.md#cases-that-wait-for-real-traffic)).

Do not turn likely landmarks into steps. The worked Machine QA Pack case
`installer-exploration` deliberately replaces the territory of the
installer campaign with one agent-chosen mission.

The campaign combines deterministic checks and missions in one environment-neutral template. Generation
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

Run just one materialized mission without starting its sibling requirements:

```text
yoke qa case run --requirement-id N
```

This creates a one-requirement plan execution using the same lease, walk,
review bundle and main-agent verdict path below, including deployment-member
missions. Exit code `12` carries the typed review continuation. Repeating the
case command reprints pending review without recapturing. An `inherit` mission
cannot run alone because its predecessor must capture in the same execution;
run the ordered plan instead. A case already owned by a standalone execution
resumes through that execution rather than creating another one.

Run the attached plan at its transition:

```text
yoke qa plan run --item PREFIX-N --transition <transition> \
  --machine <registered-name>
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
A mission that needs state that must survive — a sign-in, a session opened through the native GUI/desktop route, or a granted permission — declares `"starting_state":"as_is"` with a reason, so it requests no baseline reset, and requests any password entry only while it holds the host lease: released, the host's next turn may reset it first. Outstanding [cleanup reset debt](deployment-plan-execution.md) still requires recovery before an `as_is` mission starts. A case requiring earlier files also declares `method_config.continuity_fingerprint`; the [starting-state contract](case-attachment-rules.md#machine-case-starting-state) explains recording hashes and the `continuity_lost` refusal before setup or walking. Re-declare an unrun case with `yoke qa requirement update --field starting_state` ([case attachment](case-attachment-rules.md#machine-case-starting-state)).

## Holding a Walk, and Continuing a Settled One

A queued walk in `waiting` keeps its queue place while its owning session
has not ended, whatever the session's mode or heartbeat age. Waiting walks
cannot heartbeat. Only the owner's recorded session end makes one abandoned;
the sweep settles it with the existing `stale-heartbeat` reason.

Active walks keep the 30-minute heartbeat rule. A walker told to hold can park
(`yoke sessions touch --mode parked --reason "..."`); a live parked owner
protects its active walk from the stale sweep. An ended owner provides no
such protection. Terminal settlement stamps an unreviewed capture with an
`error` verdict.

That verdict records the execution, not a judgment on the walk, and the Test
Machine still holds every bit of state the walk built. The way back in is a
continuation:

```text
yoke qa plan run --item PREFIX-N --transition T --continue-mission
```

Host-wait and continuation commands omit `--machine`. Simultaneous cases keep
their declared driver and full host set. For single-host cases, the scheduler
recovers each platform's original host from the execution's recorded leases and runs,
including its continuation source. A platform not used before selects a fresh
eligible host; a global pin cannot represent a roster using several hosts.
Correction-ready commands also omit the pin; scheduling recovers each corrected
case's failed attempt host from its requirement replacement history.

A continuation records new runs over the same roster without resetting hosts.
Its latest runs supersede the swept `error`; the prior runs retain their
`stale-heartbeat` history.

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

Mission preparation enters `walking`; the last mission’s recorded walk-end
changes it to `awaiting_walk_review`. Ordinary captures enter review directly.
Both retain their existing verdict and host-custody rules.
