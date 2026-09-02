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

The built-in method has these immutable properties:

| Field | Value |
|---|---|
| `runner_id` | `agent_mission` |
| `verdict_path` | `agent` |
| `concurrency_mode` | `serial` |
| required capabilities | `browser-control`, `test-machine` |
| case config | `{"executor":"informed_subagent"}` or `{"executor":"naive_target_session"}` |

Capability declarations are provisioning authority. Materialization resolves
both kinds against the project capability rows and the executing harness
session. The Test Machine connection comes from the `QA_HOST:` coordination
lease recorded on `qa_plan_executions.machine_lease_id`; the mission does not
open an undeclared host or browser path.

## Authoring Shape

Write one case with broad instructions and an observable good outcome:

```json
{
  "case_key": "new-user-installation",
  "method_id": "exploratory-mission",
  "instructions": "Install as a new user, work through onboarding, and investigate confusing, broken, missing, or unsafe behavior using the terminal, browser, and visible desktop.",
  "expected_outcome": "Return a ranked actionable report, name what could not be verified and why, and return a precise handoff if a person must act.",
  "method_config": {"executor": "naive_target_session", "machine": "test-mac-pro"},
  "host_baselines": ["fresh-host"]
}
```

Omit `machine` when any registered host can run the mission. When present, it
is validated during plan authoring and becomes the case's durable
`test-machine:<name>` capability constraint.

Do not turn likely landmarks into steps. The worked Machine QA Pack case
`installer-exploration` deliberately replaces the territory of the ten-case
scripted installer campaign with one agent-chosen mission.

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
yoke qa plan run \
  --item PREFIX-N \
  --transition <transition> \
  --machine <registered-name>
```

The run pin is optional and must agree with every case-authored constraint.
Without one, admission prefers a verified free machine and reports its reason.

The plan runner reaches the declared host baseline, records a zero-artifact
mission docket, advances the full roster, creates the existing review bundle,
and parks the execution in `awaiting_agent_review`. Exit code `12` means the
typed review continuation must run now. It is not itself a human-review state.

While parked, the execution retains and heartbeats its Test Machine lease. The
returned dispatch has `dispatch_kind=main_agent_mission`. The main agent owns:

- the item, work claim, Progress Log, and operator channel;
- dispatching each case's walker according to its executor;
- combining walker returns into the primary written report;
- choosing and submitting the final verdict for every bundled case.

The walker never issues the verdict. Its turn returns one status:

- `WALK_STATUS: COMPLETE` — the walk reached a natural stopping point;
- `WALK_STATUS: HUMAN_GATE` — a person must act before it can continue;
- `WALK_STATUS: UNDETERMINED` — an essential fact could not be established for
  a reason other than a pending human action.

## Human-Gate Handoff

Subagent turns are atomic and cannot pause for the operator. At a permission
dialog, interactive sign-in, approval, or other human-only action, the walker
returns immediately with:

1. the exact action the person must take;
2. why it is required;
3. the current product state;
4. the first operation a fresh walker should perform afterward.

The main agent appends that handoff to the item's Progress Log, asks the
operator through the main channel, and dispatches a fresh walker after the gate
is cleared. The next walker reads the Progress Log. The walker never blocks a
turn waiting for the response and never silently skips the gated area.

## Substrate Access

The review dispatch supplies an exact host command template:

```text
yoke --env <connection> qa mission host-command \
  --item-id <id> \
  --execution-id <execution-id> \
  --requirement-id <requirement-id> \
  -- ARGV...
```

This command revalidates subject ownership, the parked execution, immutable
case snapshot, and retained lease before resolving client-local Test Machine
credentials. It accepts bounded argv rather than shell text and returns
redacted output. Every path in that argv names the **Test Machine's**
filesystem, never the calling machine's, so the session-cwd write-authority
guard exempts it from local write classification — a shell redirect written
after the argv still runs locally and stays enforced.

On macOS, append `--gui-session` when a command needs the login keychain or
window server. Three apparently different failures share one diagnosis:

- screenshot capture cannot create an image from the display;
- switching to the audit session is not permitted;
- a keychain-backed CLI reports OAuth expired and unrefreshable while its
  credential file is unchanged and the console session works.

They mean the command ran in the wrong session. Retry through the Terminal
GUI-session bridge before diagnosing broken credentials or privacy settings.

Use the declared browser-control substrate for web interaction. A fresh Test
Machine may not yet have its packaged browser runtime; `yoke qa browser setup`
materializes it. Setup friction is observable mission behavior, not authority
to route around the capability. The dispatch supplies both that setup command
and a lease-routed `yoke qa browser step --base-url URL --step-json JSON`
template. The walker chooses and submits one step at a time; no scenario is
authored in advance.

## Evidence Discipline

Perception is disposable. A walker may inspect hundreds of screens, DOM states,
or command outputs while deciding what to do; those observations are not
automatically evidence.

Attach only deliberate proof that makes a finding or human gate independently
understandable. The dispatch carries the single runtime-owned artifact limit,
and the shared artifact-add surface rejects attachments beyond it. Never make a
parallel run to evade the cap, and never attach credentials or secret-bearing
content.

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

Termination is guaranteed rather than hoped for. An execution that stops
reporting progress is reaped into `aborted` with `release_reason`
`stale-heartbeat` after 30 minutes without a heartbeat, and reaping is
deliberately blind to row vintage: a stranded execution written before
executions carried an execution target still settles, because resolving that
target is a precondition for *running* an execution, not for abandoning one.
For the same reason abandoning a non-progressing execution is open to any
session on its subject — the session that owned a stranded execution is by
definition the one that is no longer there — while a live execution keeps its
owner-only guard.

Reaping and withdrawal run together whenever the Inbox is read, so a reader
never sees a blocking row that blocks nothing. Run the same convergence
deliberately, with a receipt naming what was reaped, withdrawn, and retained:

```text
yoke decision-requests dispose-ended [--project-id N ...] --json
```

The pass is kind-blind: it applies each kind's own subject-state contract, so
it also releases, for example, a strategy-revision review that a later
revision has superseded.
