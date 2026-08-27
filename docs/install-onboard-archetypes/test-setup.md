# Test setup — first-class onboard dimension

Done and merged gates run the project's **registered verification command**
through QA plan cases (`qa.plan.materialize` then `yoke qa case run`). Install
and onboard today almost never bind that command. This page is the live
surface map; each archetype file records that persona's test reality against
it.

## What the two surfaces actually ask

**Wizard (`yoke onboard`).** PATH, Account, GitHub, Project, Hosting, Review.
No test, CI, QA-plan, or merge-queue question exists
(`onboard_wizard_steps.py` step map).

**Harness `/yoke onboard`.** Step 1 repo survey *reads* "test config"
(`strategy-conversation.md`). Step 2's confirmed profile now carries a
**test-setup box** with four named outcomes — surveyed command, scaffold
suite, review-only suite, or explicit skip (`profile-and-scaffold.md`). Step 5
binds the confirmed outcome and records the `verification-command-binding`
checklist row (`hosting-and-environments.md`). Step 8 attaches a reusable plan
when named and turns review-only legacy suites into item-specific blocking
review plus advisory command requirements (`seed-work.md`).

## Live bind surfaces (verified)

| Intent | Live write | What it does |
|---|---|---|
| Test trees | `yoke project-structure patch apply` family `test_roots` | Path selectors the impacted selector reads |
| Descriptive command | family `verification_profiles` payload `test_command` | **Not** the QA gate. Advance qa-seeding says do not seed free-form `quick`/`full` from project-structure command settings |
| Gate command | Plan slug `registered-command-{scope}` for `quick` / `full` / `e2e` / `smoke` | `yoke qa registered-command set --project P --scope SCOPE --command ARGV` — one call converges the plan, its case, the runner, and the project-default attachments; no environment. The same `ensure_registered_command_plan` the yoke seed calls |
| Review-only legacy suite | Item requirements: blocking `implementation_review`, non-blocking method `command` | Records the exact known-red/flaky argv without making its current failure a project-default gate |
| CI routing | `yoke projects capability-settings set --project P --cap-type ci_workflow_file --new --settings-json '{"workflow_file":"ci.yml"}'` | Filename under `.github/workflows/` (optional `scope_workflows` map). Empty declaration keeps the **local** `command` method |
| Merge queue | `yoke projects capability-settings set --project P --cap-type merge_queue --new --settings-json '{}'` | Presence-only. Template `requires` `ci_workflow_file` and `github`. Absent → standalone merge engine |
| Attach to an item | `yoke qa item-plan attach --item PREFIX-N --project P --plan-id N --transition reviewing-implementation` | Seed-work already teaches this when CURRENT-PLAN names a plan |

Routing (`qa_command_plan_registration.py` / `qa_command_scope_routing.py`):

- `quick` and `full` default `ci_routable=True`: if `ci_workflow_file` names a
  workflow, the case method is `command-ci` (`ci_run`); otherwise `command`
  (`worktree_run`).
- `e2e` and `smoke` default local (need a base URL CI often cannot reach)
  unless `scope_workflows` names a workflow for that scope.
- Unreachable `command-ci` fails with a **named reason** (not a silent local
  downgrade) — `qa_case_ci_lane.py`.
- `merge_queue` makes the QA executor open/reuse the landing PR and record
  that PR's entry run (`dash/verification-and-close.md`).

`yoke qa plan create` still **requires** `--environment`, so a plan authored
through that adapter is tied to a site. The registered-command binding above
does not go through it and needs no environment. Extending the environmentless
shape to the remaining plan-authoring surfaces is G-qa-plan-needs-env.

`webapp-scaffold` 1.1.2 installs FastAPI tests, Vitest, Playwright examples,
and `.github/workflows/ci.yml`. The Pack itself still writes neither
`ci_workflow_file` nor a `registered-command-*` plan; onboard step 5 now
declares both from the confirmed test-setup box, after the Pack has applied.

## Bind / refuse / silent mis-bind

**Can bind.** A surveyed shell command as `registered-command-quick` (and
`full` when they differ). The argv may be `mvn test`, PHPUnit, `xcodebuild`,
or `docker compose run --rm tests`; it need not resemble pytest. A real
`.github/workflows/*.yml` as
`ci_workflow_file.workflow_file`. GitHub App + that workflow + org queue
rules as `merge_queue`. Scaffold-installed `ci.yml` the same way, after
apply.

**Can describe separately.** A monorepo may carry one keyed `test_roots`
entry per tree while its reliable `quick` command covers only a documented
slice. A distinct `full` command is the aggregate. A known-red or materially
flaky suite stays review-only: preserve roots and argv, then seed blocking
human/agent review plus a non-blocking executable case per item.

**Refuses (correct, if declared).** `command-ci` when no workflow is
declared. `merge_queue` without GitHub + `ci_workflow_file`. HTTPS
`yoke migration rehearse` (unrelated, but the same honesty pattern).

**Silent mis-binds today.**

1. Writing `verification_profiles.test_command` and believing the
   reviewing-implementation gate will run it — it will not. The family
   reference and the public QA doc now both say so outright.
2. Confirming the stock profile, installing `webapp-scaffold` (tests +
   `ci.yml` land), never declaring the capability or plan — closed by the
   step-2 box plus the step-5 binding; the box has no silent default, so
   the profile cannot be confirmed without an answer.
3. Treating Jenkins / GitLab CI / Bitbucket Pipelines / `fastlane` as
   `ci_workflow_file` — that capability is a **GitHub Actions filename**.
4. Declaring `command-ci` against a workflow that deploys but does not run
   the registered command (onboard step 5: existing CI is a **hint**, not a
   contract).
5. `yoke qa plan create` forced to name a stage/prod environment that was
   created only because hosting was deferred — the plan is tied to a fiction.

## No-tests: what the QA gate should mean

For a repo with no runnable suite, the step-2 question offers these honest
paths:

1. **Offer to scaffold a minimal suite.** Greenfield + `webapp-scaffold`
   already drops tests and `ci.yml`. Existing empty idea repo: same offer.
   Content-only / pre-code: a one-file pytest or project-native equivalent.
2. **Accept an operator-attested no-tests posture.** A named project
   declaration that reviewing-implementation / done use an explicit
   `implementation_review` requirement (advance qa-seeding already seeds
   that when no plan and no ACs exist) — not a fake `pytest` and not a
   silent empty gate.
3. **Refuse with a named reason.** Correct for inventing `command-ci`,
   inventing `merge_queue`, or registering a command whose argv is not in
   the repo.

**Recommend (1) then (2).** Offer the scaffold (or the Pack's tests) at
profile confirmation. If the operator declines — idea-only, content site,
client will not pay for tests yet — record attested no-tests and seed
`implementation_review` instead of a `registered-command-quick` that cannot
run. Always refuse (3) for CI/queue lies. Never skip the question.

Registration enforces the third path where it can check: a path-shaped argv
that is not in the checkout is refused by name, because it would bind a gate
that fails wherever it runs. A bare program name the registering machine lacks
is reported rather than refused — an operator binding `mvn verify` from a
laptop for a repository whose CI has Maven is doing the right thing.

The question is now asked: the step-2 box includes scaffold and explicit-skip
outcomes, and the `verification-command-binding` checklist row records which
one was chosen.
The durable declaration for outcome (2) is the `verification_posture`
Project Structure family — a project-attached singleton whose only stored
value is `attested-no-tests`, carrying the operator's required reason. Write
it with `yoke qa no-tests attest --project P --reason "..."`; that one call
also retires any `registered-command-*` plan, so a project can never hold both
declarations. While it stands, `reviewing-implementation` seeds a blocking
`implementation_review` requirement at the transition
`registered-command-quick` would have attached to, and registering a command
for any scope is refused by name with the clearing recipe. `yoke qa no-tests
clear --project P --reason "..."` returns the project to undecided so a suite
it later gains can be bound.

## Archetype mapping

| Reality | Quick | Full | Roots and runner posture |
|---|---|---|---|
| Maven / JUnit | `mvn -q -DskipITs test` | `mvn verify` | Record each module test tree; local `command` unless an Actions test workflow runs it |
| PHPUnit | `vendor/bin/phpunit --testsuite unit` | `vendor/bin/phpunit` | PHP test roots remain separate from any frontend roots |
| XCTest | Focused `xcodebuild test` destination/scheme | Broader workspace invocation | Local `command`; `fastlane` alone is not Actions CI |
| Containerized | Focused `docker compose run --rm tests ...` | Aggregate container command | Local `command` unless a real Actions test workflow owns it |
| Monorepo | One documented reliable slice | Aggregate workspace command | One keyed `test_roots` entry per suite tree |
| Known-red / flaky | No project-default binding | No blocking full binding | Blocking `implementation_review` plus non-blocking exact command per item |

## Scopes the sample must cover

none · scaffold-only (unregistered) · local pytest/jest · GitHub Actions ·
other-CI (Jenkins/GitLab/Pipelines) · monorepo many suites · XCTest /
fastlane · flaky legacy · containerized · no-code / content.
