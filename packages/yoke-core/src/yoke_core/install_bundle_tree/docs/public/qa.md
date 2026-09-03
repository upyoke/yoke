# QA

Workbench **QA** tabs:

| Tab | Meaning |
|---|---|
| **Methods** | Registered contracts cases use to prove a claim (command, browser, …) |
| **Plans** | Project-scoped ordered cases and attachments |
| **Activity** | Readable outcomes from requirements, runs, evidence |

## How gates work

Workflows attach plans to transitions (for example reviewing-implementation).
The case run **is** the verdict-producing execution — do not hand-run the same
full suite and then re-run it through QA.

```bash
yoke qa case run --requirement-id <id>
```

## Binding your project's command

Bind a source-level command with no deployment environment flags:

```bash
yoke qa registered-command set --project <p> --scope quick --command "<argv>"
```

That converges the whole binding: the `registered-command-quick` plan, its
case, the runner the case uses, and the project-default attachments at the
gating transitions. The command is arbitrary shell argv: Maven, PHPUnit,
`xcodebuild`, and `docker compose run --rm tests` are as valid as pytest.
Register a reliable documented slice as `quick`; add `--scope full` with the
broader argv only when the two commands genuinely differ.

`quick` and `full` always materialize a project target, even when the project
has exactly one declared environment. Plan list and detail views label this
`project source · no deployment environment`.

Deployed scopes use one explicit target contract:

| Runner | `e2e` / `smoke` registration |
|---|---|
| Local, declared environment | add `--environment SITE/NAME` (or an environment ID) |
| Local, runtime URL | add `--requires-base-url`; the case run must supply HTTP(S) `--base-url` |
| CI via `scope_workflows` | add `--environment SITE/NAME`; runtime URL mode is refused |

Exactly one local deployed target is required. Invalid combinations and bad
environment references are refused before plan writes. Generic `yoke qa plan
create` remains environment-bound and still requires `--environment`.

Test roots are independent Project Structure entries. Record each monorepo
tree with a keyed `test_roots` `put`; the quick command may intentionally cover
one slice while the full command aggregates all suites.

Declaring a GitHub Actions **test** workflow routes those scopes to CI:

```bash
yoke projects capability-settings set --project <p> --cap-type ci_workflow_file \
  --new --settings-json '{"workflow_file":"ci.yml"}'
```

Without that declaration the scopes run locally in the item's worktree, which
is a correct configuration rather than a downgrade. A project-structure
`verification_profiles.test_command` entry is descriptive and is never the
gate command. Jenkins, GitLab CI, Bitbucket Pipelines, `fastlane`, and an
XCTest or container command without an Actions test workflow stay on the local
`command` method; they are not `ci_workflow_file` declarations.

Name the workflow that runs the suite. The binding refuses one the gate cannot
reach, because the gate starts a workflow by dispatching it:

- No `workflow_dispatch` trigger carrying a `yoke_dispatch_id` input — refused
  for every project; the gate could never start a run.
- No `pull_request` trigger — reported, and refused for a project declaring
  `merge_queue`, whose gate reads the landing pull request's own run.
- Not a file under `.github/workflows/`, or not a workflow at all — refused,
  naming any other CI system the repository carries.

Where the control plane holds no checkout for the project, the declaration
cannot be read and the result names that rather than guessing. The boot-time
convergence never refuses over a stale declaration: it binds the local runner
and reports the reason, so one project's rename cannot stop a fleet from
booting.

Declaring `merge_queue` requires GitHub bound, `ci_workflow_file` declared,
and that workflow carrying a `merge_group` trigger — without it the queue's
integration gate has nothing to run and a queued pull request never merges.

## When the project has no suite

A repository with nothing runnable does not get an empty gate. An empty
requirement set refuses as `GATE_QA_REQUIREMENTS_EMPTY`; it can never report
green for a review nobody performed.

Offer a minimal suite first; one real test makes a real gate. When that is
declined — an idea-only repo, a content site, a client who will not fund tests
yet — record the decision instead of inventing an argv:

```bash
yoke qa no-tests attest --project <p> --reason "<why there is no suite>"
```

The reason is required. One call records the posture and retires any
`registered-command-*` plan, so a project can never hold both declarations.
For every workflow that consumes project testing defaults, command absence
seeds a blocking `no_tests_declared` requirement where
`registered-command-quick` would have attached. Its passing run is recorded by
an agent and labeled `agent-attested / no-tests-declared`; it never implies a
suite ran. Registering any command while the explicit posture stands — the
`command-ci` runner included — is refused by name.

When the project later gains a suite, clear the posture and bind the command:

```bash
yoke qa no-tests clear --project <p> --reason "<what changed>" && yoke qa registered-command set --project <p> --scope quick --command "<argv>"
```

Registration also refuses an argv the repository provably lacks: a path-shaped
command like `vendor/bin/phpunit` that is not in the checkout is named and
rejected rather than bound as a gate that would fail wherever it ran. A bare
program name the registering machine lacks is reported, not refused — the
suite often runs somewhere that machine is not.

## Known-red and flaky suites

Do not bind a known-red or materially flaky suite as a blocking project
default merely to make it visible. Preserve its roots, exact argv, and known
condition. Seed each relevant item with a blocking `implementation_review`
requirement and a non-blocking `command` case for the suite. The advisory case
records the current result without manufacturing a green gate or making a
known baseline failure block every item.

When the project binds CI for quick/full scopes, commit and let the case
runner push the lane branch; the verdict names the CI run URL and head sha.

## Local iteration

While implementing, use impacted selection:

```bash
yoke watch pytest --impacted main --bounded
```

When the project declares a `ci_workflow_file` capability, that selection
runs on its CI against the pushed lane commit — so commit first; it refuses
an uncommitted tree and a checkout on the base branch. `--local` (or
`YOKE_PYTEST_LOCAL=1`) runs it on this machine instead, under one
machine-wide xdist worker budget.

Full-suite authority on protected merges is CI (when configured). Local full
sweeps are the CI-outage fallback.

## Browser QA

Browser methods use the packaged browser runtime. Scenario schemas live under
reference. See [reference/qa-platform.md](reference/qa-platform.md) and
[reference/browser-scenarios.md](reference/browser-scenarios.md).
