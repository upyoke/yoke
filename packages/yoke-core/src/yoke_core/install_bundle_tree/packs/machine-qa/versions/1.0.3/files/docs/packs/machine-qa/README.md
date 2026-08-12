# Machine QA Pack

Machine QA registers three reusable proof contracts:

- Terminal check drives a real terminal program through structured PTY steps.
- Terminal inspection pairs checkpoint text with real Terminal captures for a
  separate inspection verdict.
- Machine state check evaluates argv-shaped assertions on the controlled host.

All three select Yoke's approved `host_control` runner and require one
project-owned `test-machine` capability. The Pack never contains a host,
credential, test plan, or installer-specific case. Those remain project-owned
capability data and harness-authored plan content.

The capability is serial. A named host baseline and every case that depends on
it execute under one coordination lease. Baseline failure sets the capability
to `error`, emits secret-free evidence, and prevents the case from running.

Method definitions are installed at `qa/methods/machine-qa.json`. Presentation
order, glyphs, configuration-contract selection, and proof-summary selection
travel in each method definition. Installed files belong to the project and
may be customized there; the Pack receipt is only the update baseline.
