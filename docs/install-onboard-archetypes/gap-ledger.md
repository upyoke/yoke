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
| G-hosting-aws-only | missing-config-surface | deployed | Wizard: "AWS for now". Pack `vps-hosting` is EC2, not DigitalOcean. No PaaS. | A02 A04 A11 | YOK-2465 |
| G-deferred-hosting-flows | blocker | deployed / released | `/yoke onboard` step 5 still registers stage/prod and flows when hosting is deferred | A01 A02 A05 A09 A10 A12 | YOK-2466 |
| G-forge-github-only | missing-config-surface | merged | Skip GitHub works; GitLab/Bitbucket cannot bind, clone-list, or merge-queue | A06 A11 | YOK-2469 |
| G-handoff-cursor | taught | installed | Shim hand-off names Claude Code, Codex, or Cursor then `/yoke onboard` | A01 A03 A05 A09 | YOK-2468 |
| G-app-store | missing-config-surface | deployed | No TestFlight/Play/`fastlane` runner; app-store delivery remains external to Yoke | A09 | YOK-2470 |
| G-selfhost-not-in-wizard | friction | installed | Resolved: picker previews and performs guarded Compose first boot, captures the token, activates the local connection, and offers setup or handoff exits; the manual reference remains | A06 A07 | YOK-2471 |
| G-migration-undeclared | missing-config-surface | migrated | No onboard question for `migration_model` / "no DB to migrate" | A03 A06 A07 | YOK-2472 |
| G-byo-aws-identity | missing-config-surface | deployed | Hosting collects a new IAM user access key pair only | A03 A07 | YOK-2473 |
| G-idea-default-flow | blocker | released | `infer-and-create.md`: non-empty deploy-defaults **always** assigned | all with a default flow | YOK-2474 |
| G-test-setup-unasked | blocker | merged / done | Wizard and profile never ask how tests run; gates still expect a registered command | all | YOK-2477 |
| G-no-tests-posture | closed | merged / done | Closed: `verification_posture` singleton family, written by `yoke qa no-tests attest`, seeds a blocking `implementation_review` where the registered command would have run | A01 A05 A08 A10 A12 | YOK-2478 |
| G-scaffold-tests-unregistered | friction | merged / done | `webapp-scaffold` lands tests + `ci.yml`; onboard does not declare `ci_workflow_file` or `registered-command-*` | A01 A12 | YOK-2477 |
| G-ci-workflow-undeclared | friction | merged | Survey sees Actions; onboard never writes `ci_workflow_file` | A02 A03 A04 A07 A09 | YOK-2479 |
| G-command-ci-misbind | blocker | merged / done | Deploy YAML / Jenkins / GitLab / fastlane store-upload treated as the verification workflow | A03 A04 A06 A09 A11 | YOK-2479 |
| G-qa-plan-needs-env | closed | merged / done | Closed: registered `quick`/`full` plans carry a project target; deployed scopes select an environment or runtime base URL. Generic plan creation remains intentionally environment-bound | A01 A09 A12 | YOK-2480 |
| G-legacy-suite-unmapped | missing-config-surface | merged / done | JUnit/Jenkins, PHPUnit, XCTest, monorepo many suites have no scope map | A06 A07 A09 A11 | YOK-2481 |
| G-merge-queue-github-only | missing-config-surface | merged | `merge_queue` requires `ci_workflow_file` + `github`; App skip / other forge cannot declare it | A06 A07 A11 | YOK-2479 |

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

**Refuse:** `command-ci` without a declared GitHub Actions workflow that
runs that command. `merge_queue` without GitHub + `ci_workflow_file`.
Inventing `pytest` for a repo that has none.

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
- Hosting copy: `HOSTING_CONNECT_TITLE` / `HOSTING_CONNECT_SUBTITLE`
- Idea defaults: `.agents/skills/yoke/idea/infer-and-create.md` §b
- Onboard step 5 entry with deferred hosting: `hosting-and-environments.md`
- Usher Route A/B and exit 7: `.agents/skills/yoke/usher/deploy.md`
- Merge-only `target_tier`: `docs/public/reference/db-reference/projects-and-flows.md`
- QA scopes and `command` vs `command-ci`: `qa_command_plan_registration.py`
- `ci_workflow_file` / `merge_queue` templates: `projects_seed_ci_workflow.py`
- Registered-command target matrix: `qa_command_plan_registration.py`
