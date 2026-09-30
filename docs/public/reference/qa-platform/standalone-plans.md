# Standalone Project QA Plans

Run a saved plan immediately without an item or deployment run:

```text
yoke qa plan run --plan PLAN --project P
```

Each fresh run freezes cases and host baselines in saved order in existing QA
execution, requirement, run, review, and artifact records. Its standalone execution
owns the evidence and changes no item transition, delivery acceptance, or stage gate.
An interrupted live run resumes its immutable roster and cursor in its owning session.
Unsupported runners or missing capabilities refuse before any case executes.

Commands require `--checkout-path PATH --expected-sha FULL_SHA`: the checkout
must be clean at that commit. CI cases require the SHA and `--expected-branch REF`,
a published branch or tag at that commit, and a case-declared `ci_workflow`.
They dispatch with declared `ci_workflow_inputs`, verify the run's actual commit,
and record its URL and conclusion. Manual CI does not publish, rebase, or open a
landing PR, including on merge-queue projects.

Browser, terminal, machine-state, inspection, and exploratory cases retain their
target, capability, serial lease, evidence, and review contracts.
Read proof with `yoke qa plan get PLAN --project P --full`, then inspect returned
requirement and run ids through QA reads. Abort with
`yoke qa plan abort --project P --execution-id ID --reason TEXT`.
`--continue-mission` resumes a stale-settled mission with its unchanged plan snapshot
and preserved host state. Read `yoke qa plan run --help` for the complete requirements.

## Function protocol

Standalone project QA uses `qa.plan_execution.begin` with a project-scoped
`global` target and payload `plan`, optional `source_revision`, `source_ref`,
`checkout_path`, `machine`, and `continue_mission`. Adapter:
`yoke qa plan run --plan PLAN --project P`; read its `--help` for source bindings.
State, heartbeat, advance, complete, abort, review, and machine/mission calls
retain that target and verify the execution's project and actor/session.
Responses carry `standalone_plan_id`; snapshots and proof reads carry
`standalone_execution_id`. Requirement-targeted recording verifies the same
owner, and browser context accepts a standalone `qa_requirement` target.
These changes require the next serving release. They use existing QA records
and never credit item or deployment gates.

