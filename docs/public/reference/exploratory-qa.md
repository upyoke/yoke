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
  "method_config": {"executor": "naive_target_session"},
  "host_baselines": ["fresh-host"]
}
```

Do not turn likely landmarks into steps. The worked Machine QA Pack case
`installer-exploration` deliberately replaces the territory of the ten-case
scripted installer campaign with one agent-chosen mission.

Choose the executor per case:

- `informed_subagent` isolates the walk while supplying the relevant project
  and Progress Log context.
- `naive_target_session` starts a separate agent session on the target machine.
  A fresh machine without a project checkout is naive by construction. Do not
  add a checkout or project internals to make the walk easier.

## Execution and Review

Run the attached plan at its transition:

```text
yoke qa plan run \
  --item PREFIX-N \
  --transition <transition>
```

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
redacted output.

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

Include exactly one row for every bundle case. `undetermined` requires a
non-empty rationale naming what could not be established and why. That
rationale is persisted as `qa_runs.verdict_reason`, the verdict never satisfies
an all-pass aggregate, and the ordinary review/operator-decision path is
created. Do not map it to pass or fail and do not use retired verdict terms.
