# Machine QA Pack

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).

Machine QA registers four reusable proof contracts:

- Terminal check drives a real terminal program through structured PTY steps.
- Terminal inspection pairs checkpoint text with real Terminal captures for a
  separate inspection verdict.
- Machine state check evaluates argv-shaped assertions on the controlled host.
  An assertion that sets `required_session_context` to `gui` executes through
  the logged-in macOS Terminal.app session so it can use the window server and
  login keychain.
- Exploratory mission gives one prose mission to a main-owned QA run. A case
  selects an informed subagent or a context-naive target-machine session as its
  walker. The walker chooses the sequence; deterministic checks still belong
  on Command methods because they are faster, cheaper, and repeatable.

The three scripted methods use Yoke's approved `host_control` runner and
require `test-machine`. Exploratory mission uses `agent_mission` and formally
requires both `test-machine` and `browser-control`; an undeclared substrate is
not provisioned. The Pack contains no host or credential. Those remain in
project-owned capability records and machine-local capability secret files.

Every machine-run case declares the state it starts from: `host_baselines`
naming `fresh-host` or `shell-preconfigured` (reset before, restored after),
`"starting_state": "inherit"` to continue on the machine the preceding case
left, or `"starting_state": "as_is"` with a `starting_state_reason`. Authoring
and materialization refuse an undeclared case. An exploratory mission cannot
inherit; it is walked after the plan's other cases. Its printed `walk-start`
command resets to its baseline and restores any `host_starting_state` package
fixture; `walk-end` restores the baseline and records that on the run. Machine
pins are accepted by both authoring and execution validation for scripted
checks.

The test machine is serial. A named host baseline and every dependent action
execute under one coordination lease. An exploratory mission keeps that lease
while its execution is parked in `awaiting_agent_review`, then releases it on
review submission or abort.

Host preparation, privacy/sign-in context, desktop access, save/restore and
recovery live only in the [per-OS procedures](host-provisioning.md).
Use the procedure for the declared OS before scheduling a machine-backed run.

The main agent owns the item, operator channel, report, and final verdict.
The agent holding the Test Machine lease owns every Yoke project it creates
during the walk. It appends each project's slug to the verified item's Progress
Log the moment the project exists, so a replacement can finish the cleanup, and
before returning either a pass or failure it retires each one with its own
control-plane CLI (`yoke projects retire --project SLUG --reason ...`) — never
with Yoke on the Test Machine, which needs no Yoke install at all. Retirement
never deletes project history; a retirement blocker is a finding with its
recovery. The mission's printed `yoke qa mission walk-end` command then
removes secret staging with plain OS commands and restores the starting state.
Walk missions one at a time; they share the plan's one Test Machine.

Walkers are atomic. Agents complete setup and application steps that do not
need the user; the user completes personal credential steps. At a human gate a
walker returns the exact action and resume state; the main agent records it in
the item's Progress Log, asks the operator, then dispatches a fresh walker. Routine perception is discarded. A mission may
not exceed the runtime-supplied artifact limit across its run.

Agent verdicts are `pass`, `fail`, or `undetermined`. An `undetermined` verdict
must name what could not be established and why; it requests an operator
decision and never satisfies an all-pass aggregate.

Method definitions install at `qa/methods/machine-qa.json`. The one-case
installer example installs at `qa/examples/installer-exploration.json` and is
the agent-chosen inverse of a deterministic campaign. The provisioning
procedure installs beside this README at
`docs/packs/machine-qa/host-provisioning.md`. Installed files belong to the
project and may be customized there; the Pack receipt is only the update
baseline.

## Host prerequisites

[macOS](macos-host-provisioning.md), [Linux](linux-host-provisioning.md) and
[Windows/WSL2](windows-host-provisioning.md) each provide the complete ordered
procedure and its audit. [Browser profile preparation](browser-profile-baseline.md)
links to the same separate-profile procedure for each OS. Capability records own QA leases; capacity
registrations own launches and relays, independently.

Local browser captures do not take a Test Machine lease. Every browser profile
has its own daemon, state file, log and OS-assigned port, so different projects
can capture concurrently on one host. Same-profile cases reuse their daemon
with separate owned pages and shared cookies. Stop, status, retry cleanup and
idle exit apply only to the selected profile; authorization stops only the
daemon holding that project's profile. A startup retry never stops a healthy
daemon or another profile's capture.

## Run a saved plan without an item

`yoke qa plan run --plan PLAN --project P` creates a standalone execution.
Cases and baselines keep their saved order, and terminal, machine-state,
inspection, and exploratory methods retain the same serial lease and evidence
contracts. Results use ordinary QA runs and artifacts without crediting an item
or deployment gate. Unsupported capabilities refuse before cases execute.

Commands require a clean checkout at the full declared SHA; CI also names a
published ref and the case's workflow. Manual CI dispatch keeps declared inputs
and never publishes a lane. Abort with
`yoke qa plan abort --project P --execution-id ID --reason TEXT`.
A stale-settled mission can use `--continue-mission` with its unchanged plan
snapshot to preserve host state. Read `yoke qa plan run --help` before executing.
