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
  uses an informed subagent on the controller to drive a fresh target without
  a source checkout. The walker chooses the sequence; deterministic checks still belong
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
and materialization refuse an undeclared case. An exploratory mission may
inherit only at the end of a chain with the same driver machine. Nothing may
inherit after it. Item and deployment runs isolate the entire chain; a
standalone plan must contain only that chain or refuse with
`inherited_mission_requires_isolated_plan`. Use a separate plan or attach the
plan to an item or deployment. A driver change refuses with
`inherited_driver_mismatch`; keep the driver or start a new independent chain.
Older serving releases that reject mission inheritance must be upgraded before
retrying the saved plan.

All hosts declared across a chain are reserved before its first preparation
and retained through execution and mission review. A lost companion lease
refuses continuation rather than reacquiring it. The printed `walk-start`
command applies the declared starting state: a baseline resets the host and
restores any `host_starting_state` package fixture; `inherit` continues the
preceding case's state, and `as_is` preserves the current state. `walk-end`
restores the chain's declared baseline, or records no restore when the chain
has none, and records cleanup on the run. Machine pins
are accepted by both authoring and execution validation for scripted checks.

The test machine is serial. A named host baseline and every dependent action
execute under one coordination lease. An exploratory mission keeps that lease
while its execution is parked in `walking`, then releases it on
review submission or abort.

Host preparation, privacy/sign-in context, desktop access, save/restore and
recovery live only in the [per-OS procedures](host-provisioning.md).
Use the procedure for the declared OS before scheduling a machine-backed run.

The main agent owns the item, human-request route, report, and final verdict.
A walk creates Yoke projects only by installing them on the Test Machine. The
mission's printed `yoke qa mission walk-end` command disposes of them, on a
finished or an aborted walk and before it restores anything: it uninstalls
every project the host registers, cancels its open items, retires it and
records `fixture_project_disposal` receipts on the run. It acts only on
projects created while the execution was live that the walking actor
administers, and refuses an ended execution. A project the actor does not
administer is named for an administrator to retire and never blocks walk-end. Retirement never deletes project history;
a disposal blocker exits walk-end non-zero with its recovery. Walk-end then
removes secret staging with plain OS commands and restores the starting state.
Walk missions one at a time; they share the plan's one Test Machine.

Walkers are atomic. Agents do every step an agent physically can: drive the
leased desktop, open harnesses, choose permission modes, type codes and approve
codes in the signed-in browser or with `yoke machines approve`. Only entering
the user's password or credential is a human gate. There a walker returns that
one entry and the resume state and does not send Fleet mail.
The main agent records it in the item's Progress Log, asks a live covering
steering seat or else the item's human owner, then dispatches a fresh walker. Routine perception is discarded. A mission may
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
procedure and its audit. [Browser identities](browser-identities.md) links to
the live identity procedure for each OS. Capability records own QA leases; capacity
registrations own launches and relays, independently.

Local browser captures do not take a Test Machine lease. Every browser profile
has its own daemon, state file, log and OS-assigned port, so different projects
can capture concurrently on one host. Same-profile cases reuse their daemon
with separate owned pages and shared cookies. Stop, status, retry cleanup and
idle exit apply only to the selected profile. A human sign-in stops every
daemon on the host and refuses new ones until its window closes. A startup
retry never stops a healthy daemon or another profile's capture.

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

## Live-session installer exploration

The installer example covers real agent sessions, received context and first
meaningful work reaching its actual done state. The walker chooses its route
through representative new and mature projects, resume and a second machine.
The walker opens interactive sessions through the native GUI/desktop route
and chooses each permission mode itself; only a password entry is a human
gate. Report missing modes, unavailable behavior and password gates explicitly;
installed files and a merge alone do not establish the promised outcome.

Linux hosts finish with [Linux baseline capture and recovery](linux-baseline-recovery.md):
standard probes, the save/reset roundtrip and named sealed-state recovery.

After every mission records walk-end, the execution changes from `walking`
to `awaiting_walk_review`; both retain the pending verdict bundle and custody.
