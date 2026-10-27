# Machine QA

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > Machine QA
<!-- /yoke:breadcrumbs -->

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
not provisioned. Yoke contains no project host or credential. Those remain in
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
A walk cleans up everything it creates, such as repositories, accounts and
records the product registered, with the product's own commands, and reports
anything it could not remove. The mission's printed `yoke qa mission walk-end`
command, on a finished or an aborted walk, only removes secret staging with
plain OS commands and restores the starting state.
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

These four methods ship in core Yoke and are available without installing a pack.
The installer exploration example is owned by core Yoke and feeds the saved
`installer-exploration` plan. Host procedures ship under
`.yoke/docs/verification/test-machines/`; project records own hosts and credentials.

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

<!-- yoke:contents -->
- [Host provisioning](host-provisioning.md) — Choose an OS procedure and declare the project-owned host inventory.
- [Setup responsibilities](setup-responsibilities.md) — Separate agent actions from personal credential entry.
- [Administrator commands](administrator-commands.md) — Use stored host credentials for bounded administrator commands.
- [macOS host provisioning](macos-host-provisioning.md) — Prepare the test account, privacy permissions and terminal control.
- [macOS baseline recovery](macos-baseline-recovery.md) — Save and prove macOS baselines and live browser identities.
- [Linux host provisioning](linux-host-provisioning.md) — Prepare Linux accounts, harnesses and a durable desktop.
- [Linux browser identities](linux-browser-identities.md) — Authorize desktop browser identities and approval gates.
- [Linux baseline recovery](linux-baseline-recovery.md) — Capture and prove Linux baselines and diagnose restore failures.
- [Linux live state](linux-live-state.md) — Preserve live harness installations and recover reset state.
- [Codex on Linux](codex-on-linux.md) — Configure scoped sandbox posture and recover embedded helpers.
- [Windows host provisioning](windows-host-provisioning.md) — Prepare a Windows test account and the WSL desktop route.
- [WSL browser identities](windows-browser-identities.md) — Authorize browser identities in the WSL test desktop.
- [Machine browser identities](browser-identities.md) — Follow the browser identity procedure for the declared OS.
<!-- /yoke:contents -->
