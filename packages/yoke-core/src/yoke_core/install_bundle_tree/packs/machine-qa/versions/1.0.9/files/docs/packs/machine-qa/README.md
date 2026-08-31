# Machine QA Pack

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

The test machine is serial. A named host baseline and every dependent action
execute under one coordination lease. An exploratory mission keeps that lease
while its execution is parked in `awaiting_agent_review`, then releases it on
review submission or abort. On macOS, screenshot, audit-session, and apparently
expired/unrefreshable OAuth failures from SSH are all wrong-session signals;
window-server or login-keychain commands must use the Terminal GUI bridge.
Privacy grants follow the process macOS attributes as the controller: Remote
Login UI actions are attributed to `/usr/libexec/sshd-keygen-wrapper`, while
GUI-bridge screen capture is attributed to Terminal.app. Provision and verify
those paths independently instead of granting every permission to Terminal.
Whole-home goldens have a second boundary: every captured entry is owned by the
test user, and reset prepares only non-preserved live destinations for removal.
Read-only caches and delete-denying macOS ACLs are restored from the sealed
source; the source itself is never made writable or modified.

Prepare the host before saving a `test-machine` capability. The procedure —
disk encryption, automatic login, sleep, remote access and its separate full
disk access grant, developer tools, privacy grants, and authenticated harness
CLIs — is [host-provisioning.md](host-provisioning.md), with an observable
check for every step. It sits on the same substrate boundary as the GUI bridge
rule above. A host that skips a step usually fails later in a way that reads as
agent confusion rather than as missing machine state.

The main agent owns the item, operator channel, report, and final verdict.
Walkers are atomic. At a human gate a walker returns the exact action and resume
state; the main agent records it in the item's Progress Log, asks the operator,
then dispatches a fresh walker. Routine perception is discarded. A mission may
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
