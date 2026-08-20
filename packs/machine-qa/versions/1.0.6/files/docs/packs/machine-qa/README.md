# Machine QA Pack

Machine QA registers three reusable proof contracts:

- Terminal check drives a real terminal program through structured PTY steps.
- Terminal inspection pairs checkpoint text with real Terminal captures for a
  separate inspection verdict.
- Machine state check evaluates argv-shaped assertions on the controlled host.
  An assertion that sets `required_session_context` to `gui` executes through
  the logged-in macOS Terminal.app session so it can use the window server and
  login keychain.

All three select Yoke's approved `host_control` runner and require one
project-owned `test-machine` capability. The Pack never contains a host,
credential, test plan, or installer-specific case. Those remain project-owned
capability data and harness-authored plan content.

The capability is serial. A named host baseline and every case that depends on
it execute under one coordination lease. Baseline failure sets the capability
to `error`, emits secret-free evidence, and prevents the case from running.
Known macOS session-context failures carry an explicit degraded reason; failure
to obtain a declared GUI session can never satisfy an assertion's expected exit.

An agent inspection records `pass`, `fail`, or `undetermined`. An
`undetermined` verdict must name what could not be established and why, and it
always requests an operator decision rather than satisfying the plan.

Method definitions are installed at `qa/methods/machine-qa.json`. Presentation
order, glyphs, configuration-contract selection, and proof-summary selection
travel in each method definition. Installed files belong to the project and
may be customized there; the Pack receipt is only the update baseline.
