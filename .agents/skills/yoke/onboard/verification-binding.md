# Onboard Step 5: Bind The Confirmed Verification Command

The verification half of step 5, split out of
[hosting-and-environments.md](hosting-and-environments.md) because that file
reached the authored-file line limit. It applies the test-setup box the
operator confirmed in step 2 and is independent of the hosting branch: a
project with no managed host still binds its gate here.

## Bind the confirmed test setup

This applies the test-setup box the operator confirmed in step 2. It runs here,
after the scaffold Pack has landed its tests and its `.github/workflows/ci.yml`,
so the declaration describes files that actually exist.

**A surveyed command or a scaffold suite** binds in one call per scope:

```bash
yoke qa registered-command set --project {project} --scope quick --command "{quick_argv}"
```

Add the `full` scope only when its argv genuinely differs from `quick`:

```bash
yoke qa registered-command set --project {project} --scope full --command "{full_argv}"
```

The command value is the repo's exact shell argv, not a pytest-shaped field.
Maven, PHPUnit, XCTest, and containerized suites are ordinary examples:
`mvn -q -DskipITs test`, `vendor/bin/phpunit --testsuite unit`,
`xcodebuild test -scheme App`, or `docker compose run --rm tests`. Keep a
fast reliable slice in `quick`; bind the broader invocation separately as
`full` rather than pretending the same command represents both scopes.

One call converges the whole binding — the `registered-command-{scope}` plan,
its case row, the runner the case uses, and the project-default attachments at
the transitions that gate. `quick` and `full` are project-targeted: omit both
target flags even when the project has one or more environments. They run from
the project source in the item's worktree or in CI.

For local `e2e` and `smoke`, select exactly one deployed target contract:

```bash
yoke qa registered-command set --project {project} --scope e2e --command "{e2e_argv}" --environment {site}/{environment}
yoke qa registered-command set --project {project} --scope smoke --command "{smoke_argv}" --requires-base-url
```

The first binds a declared environment. The second requires the case runner to
supply an HTTP(S) `--base-url`. When `scope_workflows` routes either deployed
scope through CI, `--environment` is required and `--requires-base-url` is
refused. Registration validates the combination before writing the plan.

**Only when a GitHub Actions test workflow runs that command**, declare it
first, so the binding above routes the case to CI instead of the local runner:

```bash
yoke projects capability-settings set --project {project} --cap-type ci_workflow_file \
  --new --settings-json '{"workflow_file":"{ci_yml_filename}"}'
```

Name the **test** workflow — the one that runs the registered command. A deploy
or release workflow is not a verification workflow; declaring one there makes
the gate report a green that proves nothing. Jenkins, GitLab CI, Bitbucket
Pipelines, `fastlane`, and an XCTest or container command without a matching
Actions test workflow are not `ci_workflow_file`; keep those scopes on the
local `command` runner. With no declaration the scopes keep that runner, which
is a correct outcome, not a downgrade.

The binding refuses a workflow the gate cannot reach, and names why. The gate
starts a run by dispatching the workflow with a `yoke_dispatch_id` input, so
`on:` must carry `workflow_dispatch` declaring that input — without it
registration refuses, because no run could ever start. `pull_request` is the
second trigger to look for: without it the gate still dispatches, but pays a
second suite on every run instead of reusing the pull request's own, and a
merge-queue project is refused outright since the queue lands only through
pull requests. Where this machine holds no checkout the declaration cannot be
read, and the result says so rather than guessing.

Offer the merge queue only when GitHub is bound, that test workflow is
declared, and it carries `merge_group:` among its `on` triggers. Creating the
row enforces the first two and reads the third from the workflow; each missing
piece refuses by name.

```bash
yoke projects capability-settings set --project {project} --cap-type merge_queue \
  --new --settings-json '{}'
```

**A review-only suite** registers no project-default command. Carry its test
roots, exact legacy argv, and known-red or flaky condition into step 8. Each
seeded item then gets a blocking `implementation_review` requirement plus a
non-blocking `command` requirement for the declared argv. This records the
suite's current result without letting it manufacture either a green gate or a
permanent blocking failure.

**An attested no-tests posture** records the decision as a project row rather
than leaving it as an omission:

```bash
yoke qa no-tests attest --project {project} --reason "{why this project has no suite to bind}"
```

The reason is required — it is what makes the row an attestation, and it is
included in the gate evidence explaining why no command ran. One call records
the posture and retires any `registered-command-*` plan, so the declarations
cannot both stand. Any workflow that consumes project testing defaults already
seeds a blocking `no_tests_declared` requirement when no command is registered;
the agent records it as `agent-attested / no-tests-declared`, never as an
executed test. Registering a command — the `command-ci` runner included — is
refused until the posture is cleared with `yoke qa no-tests clear --project
{project} --reason "{what changed}"`.

A `verification_profiles.test_command` entry in the policy rows below is
descriptive only. It is never read by the gate, so writing it is not a
substitute for the binding above.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status verification-command-binding=configured \
  --evidence verification-command-binding="roots {test_roots}; quick {quick_argv}; full {full_argv|same-as-quick}; suite health {suite_health}; runner {command|command-ci} because {runner_rationale}; {ci_workflow_file or 'no Actions test workflow declared'}"
```

For an attested no-tests posture, mark `verification-command-binding=configured`
with the attestation as evidence — something was written down, and a later
reader must be able to tell an attested project from one nobody asked. Reserve
`not-needed` for a project that genuinely has nothing to bind and nothing to
attest, and `deferred` for the operator who has not decided yet. When the argv
cannot be verified against the repo, mark it `blocked` with the missing
executable named; the registration refuses that argv by name rather than
binding a gate that would fail wherever it ran.

For a review-only suite, mark `verification-command-binding=configured` with
evidence such as `review-only suite: roots {test_roots}; argv {legacy_argv};
suite health {known_condition}; runner advisory command because the suite is
not expected green; no project-default command; blocking implementation_review
plus advisory command requirements at seeding`.
