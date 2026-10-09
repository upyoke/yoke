# Onboard Step 5: Bind The Confirmed Verification Command

Independent of hosting; execute after scaffold tests/workflow actually exist.
This applies step 2's accepted box, not a descriptive policy entry.

## Real or scaffold suite

Declare an eligible Actions test workflow **before** command registration.
Otherwise keep the local `command` runner. A deploy or release workflow is
not a verification workflow. Jenkins, GitLab CI, Bitbucket Pipelines,
fastlane/XCTest/container jobs without matching Actions tests are
not `ci_workflow_file`.

```bash
yoke projects capability-settings set --project {project} --cap-type ci_workflow_file --new --settings-json '{"workflow_file":"{ci_yml_filename}"}'
```

The gate requires `workflow_dispatch` with `yoke_dispatch_id`.
`pull_request` enables reuse rather than a second suite and is mandatory for
queue projects. An unreachable/unreadable workflow is a named refusal,
never guessed. Offer the queue only when GitHub is bound, that test workflow
is declared and its `on` includes `merge_group`; creation enforces all three:

```bash
yoke projects capability-settings set --project {project} --cap-type merge_queue --new --settings-json '{}'
```

Bind exact project-native shell argv per scope; Maven, PHPUnit, XCTest and
container commands are valid. Keep a reliable fast `quick`; register
`full` only when genuinely broader/different. One call converges plan,
case, runner and project-default gate attachments.

```bash
yoke qa registered-command set --project {project} --scope quick --command "{quick_argv}"
yoke qa registered-command set --project {project} --scope full --command "{full_argv}"
```

`quick` and `full` are project-targeted: omit both target flags even when
environments exist. For local deployed scopes select exactly one target:

```bash
yoke qa registered-command set --project {project} --scope e2e --command "{e2e_argv}" --environment {site}/{environment}
yoke qa registered-command set --project {project} --scope smoke --command "{smoke_argv}" --requires-base-url
```

Environment binds a registered target; the other requires runner HTTP(S)
`--base-url`. When scope_workflows routes a deployed scope through
CI, `--environment` is required and `--requires-base-url` refused.
Registration validates the combination before writing the plan.

## Review-only or no tests

A review-only suite has no project-default command. Carry exact roots/legacy
argv/known-red or flaky condition into step 8: each item gets a
blocking `implementation_review` requirement plus non-blocking `command` evidence.
Do not manufacture a green or a permanently failing blocking gate.

An attestation requires the operator's reason and retires
`registered-command-*` plans; both postures cannot coexist:

```bash
yoke qa no-tests attest --project {project} --reason "{why there is no suite to bind}"
yoke qa no-tests clear --project {project} --reason "{what changed}"
```

Default-consuming workflows structurally seed blocking review when no command
is registered. Record `agent-attested / no-tests-declared`, never executed
test proof. New command registration, including command-ci, refuses until clear.
`verification_profiles.test_command` describes tests; the gate never reads it.

## Row evidence

```bash
yoke onboard checklist --run-id {run_id} --row-status verification-command-binding=configured --evidence verification-command-binding="roots {test_roots}; quick {quick_argv}; full {full_argv|same-as-quick}; suite health {suite_health}; runner {command|command-ci} because {runner_rationale}; {Actions test workflow or no declaration}"
```

For an attested no-tests posture, mark `verification-command-binding=configured`
with reason/attestation evidence. Review-only is also configured, naming roots,
argv, health, advisory command, no default, blocking review and advisory seeding.
Reserve not-needed for nothing to bind **and** nothing to attest;
`deferred` for the operator who has not decided.
Unverifiable argv is blocked with the missing executable and exact refusal.
