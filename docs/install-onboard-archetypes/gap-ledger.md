# Gap ledger — install and onboard vs external archetypes

Each row is a missing or unteachable declaration. Severity classes:

- **blocker** — the archetype cannot complete install or cannot reach `done`
  without lying to Usher/idea.
- **friction** — they can proceed only by skipping and ignoring stock
  proposals.
- **missing-config-surface** — no place to declare the structure they have.
- **missing-teaching** — the surface exists but the named path is wrong or
  incomplete.

Follow-up items are filed on project `yoke` after this document; IDs are
filled in the last column.

| ID | Severity | Lifecycle claim | Missing / unteachable declaration | Archetypes | Item |
|---|---|---|---|---|---|
| G-windows-native | blocker | installed | Native OS gate is a one-line `fail`; no WSL recipe (unlike uv-decline) | A04 A08 | YOK-2464 |
| G-hosting-aws-only | missing-config-surface | deployed | Wizard declares AWS, self-hosted, or deferred; managed `vps-hosting` remains EC2-only and no PaaS apply exists | A02 A04 A11 | YOK-2465 |
| G-deferred-hosting-flows | blocker | deployed / released | `/yoke onboard` step 5 still registers stage/prod and flows when hosting is deferred | A01 A02 A05 A09 A10 A12 | YOK-2466 |
| G-forge-github-only | missing-config-surface | merged | Skip GitHub works; GitLab/Bitbucket cannot bind, clone-list, or merge-queue | A06 A11 | YOK-2469 |
| G-handoff-cursor | taught | installed | Shim hand-off names Claude Code, Codex, or Cursor then `/yoke onboard` | A01 A03 A05 A09 | YOK-2468 |
| G-app-store | missing-config-surface | deployed | No TestFlight/Play/`fastlane` runner; app-store delivery remains external to Yoke | A09 | YOK-2470 |
| G-selfhost-not-in-wizard | friction | installed | Resolved: picker previews and performs guarded Compose first boot, captures the token, activates the local connection, and offers setup or handoff exits; the manual reference remains | A06 A07 | YOK-2471 |
| G-migration-undeclared | closed | migrated | Closed: the step-2 profile carries a governed-database box and step 5 records the answer on `migration-model-setup` — a declared `migration_model`, a named model to attach later, or an affirmative `not-needed` stating that work items keep `db_claim` `none` | A03 A06 A07 | YOK-2472 |
| G-byo-aws-identity | missing-config-surface | deployed | AWS accepts guided or existing access keys; role, SSO/OIDC, instance-profile, and web-identity execution remain unsupported | A03 A07 | YOK-2473 |
| G-idea-default-flow | blocker | released | `infer-and-create.md`: non-empty deploy-defaults **always** assigned | all with a default flow | YOK-2474 |
| G-test-setup-unasked | blocker | merged / done | Wizard and profile never ask how tests run; gates still expect a registered command | all | YOK-2477 |
| G-no-tests-posture | closed | merged / done | Closed: `verification_posture` singleton family, written by `yoke qa no-tests attest`, seeds a blocking `implementation_review` where the registered command would have run | A01 A05 A08 A10 A12 | YOK-2478 |
| G-scaffold-tests-unregistered | friction | merged / done | `webapp-scaffold` lands tests + `ci.yml`; onboard does not declare `ci_workflow_file` or `registered-command-*` | A01 A12 | YOK-2477 |
| G-ci-workflow-undeclared | closed | merged / done | Closed: the step-1 survey classifies each workflow by purpose and the step-2 profile proposes `ci_workflow_file` for the test workflow only | A02 A03 A04 A07 A09 | YOK-2479 |
| G-command-ci-misbind | closed | merged / done | Closed: registration reads the named file and refuses one the gate cannot start — absent, not an Actions workflow, or no `workflow_dispatch` / `yoke_dispatch_id` input — naming any other CI system the repo carries | A03 A04 A06 A09 A11 | YOK-2479 |
| G-qa-plan-needs-env | closed | merged / done | Closed: registered `quick`/`full` plans carry a project target; deployed scopes select an environment or runtime base URL. Generic plan creation remains intentionally environment-bound | A01 A09 A12 | YOK-2480 |
| G-legacy-suite-unmapped | missing-config-surface | merged / done | JUnit/Jenkins, PHPUnit, XCTest, monorepo many suites have no scope map | A06 A07 A09 A11 | YOK-2481 |
| G-merge-queue-github-only | closed | merged / done | Closed: the `requires` list on the capability template is enforced at row creation, plus the `merge_group` trigger it cannot express; a project without GitHub is refused by name and keeps the standalone merge engine | A06 A07 A11 | YOK-2479 |

## Declare / refuse / instead (crux)

### Deployment, environment, release

**Declare:** execution profile must record one of: persistent env + flow;
merge-only flow; or **no flow**. Hosting deferred ⇒ last two only.

**Refuse:** Usher Route B / `deployment-runs start-for-item` when no
environment exists. Idea must not pass `--deployment-flow` when defaults are
empty. If a persistent flow is set and `--skip-deploy` is used: exit 7
(`usher/deploy.md`) — that refusal is correct **if** the flow was intentional.

**Instead:** Route A `yoke watch merge done-transition -- PREFIX-N --skip-deploy`
for an empty/`-internal` flow or any registered flow whose `target_tier` is
empty. Seed-work omits `--deployment-flow` when `deploy-defaults get` prints
nothing and attaches a configured merge-only default when it prints one.

### Merge target

**Declare:** GitHub App bind, or local default branch (prompt
"Pick the default branch.", default `main`).

**Refuse:** GitHub PR/merge-queue/Actions OIDC when GitHub is skipped or the
App cannot see the repo (`disabled` / pending install).

**Instead:** local engine merge; other forges stay operator-owned.

### Migration

**Declare:** project `migration_model` capability when the repo has a DB
cutover. Onboard does not ask.

**Refuse:** `yoke migration rehearse` on HTTPS product connections; rehearsal
needs a validation DB.

**Instead:** no governed mutation (`db_claim` state `none`) until declared.

### Test setup (done / merged gate)

**Declare:** at profile confirmation — one of: registered
`registered-command-quick` (and `full` if different) plus optional
`ci_workflow_file` / `merge_queue`; or an operator-attested no-tests
posture. Surfaces in [test-setup.md](test-setup.md).

**Refuse:** `command-ci` against a workflow the gate cannot start — absent
from `.github/workflows/`, not an Actions workflow, or carrying no
`workflow_dispatch` / `yoke_dispatch_id` input; and, for a merge-queue
project, one with no `pull_request` trigger. `merge_queue` without GitHub +
`ci_workflow_file`, or whose workflow has no `merge_group` trigger. Inventing
`pytest` for a repo that has none.

**Instead:** offer scaffold (or Pack tests) first; if declined, attested
no-tests → seed `implementation_review`. Local `command` when CI is not
GitHub Actions. Never write `verification_profiles.test_command` and
treat it as the gate.

### Installed (OS / PATH / uv)

**Declare:** Darwin/Linux only in the shim. uv consent. PATH doctor in the
wizard.

**Refuse:** native Windows `fail`. uv decline with manual install + rerun.

**Instead:** WSL Linux path — named, not taught.

## Source pins

- Shim OS gate and uv consent: `packaging/public-installer/install`
- Hosting copy: `HOSTING_PROVIDER_TITLE` / `HOSTING_AWS_SIGN_IN_TITLE`
- Idea defaults: `.agents/skills/yoke/idea/infer-and-create.md` §b
- Onboard step 5 entry with deferred hosting: `hosting-and-environments.md`
- Usher Route A/B and exit 7: `.agents/skills/yoke/usher/deploy.md`
- Merge-only `target_tier`: `docs/public/reference/db-reference/projects-and-flows.md`
- QA scopes and `command` vs `command-ci`: `qa_command_plan_registration.py`
- `ci_workflow_file` / `merge_queue` templates: `projects_seed_ci_workflow.py`
- Registered-command target matrix: `qa_command_plan_registration.py`
