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
the agent-chosen inverse of a deterministic campaign. Installed files belong
to the project and may be customized there; the Pack receipt is only the update
baseline.
