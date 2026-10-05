# Install and onboard support

Internal: source-maintainer reference for external project archetypes.

Current support comes from the project execution profile, declared capabilities,
and registered command refusals. Use the declaration and recovery guidance below
to assess a target; do not infer support from a past work-item outcome.

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

**Declare:** GitHub App bind, or the local default branch in the prefilled
Project details form (default `main`).

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

**Instead:** offer scaffold (or Pack tests) first; if declined, command
absence seeds `no_tests_declared` for workflows consuming project defaults.
Use local `command` when CI is not GitHub Actions. Never write
`verification_profiles.test_command` and treat it as the gate.

### Installed (OS / PATH / uv)

**Declare:** Darwin/Linux only in the shim. uv installs automatically, no
consent. PATH doctor in the wizard.

**Refuse:** native Windows `fail`. uv install failure with manual install +
rerun.

**Instead:** WSL Linux path — named, not taught.

## Source pins

- Shim OS gate and automatic uv install: `packaging/public-installer/install`
- Hosting copy: `HOSTING_PROVIDER_TITLE` / `HOSTING_AWS_SIGN_IN_TITLE`
- Idea defaults: `.agents/skills/yoke/idea/infer-and-create.md` §b
- Onboard step 5 entry with deferred hosting: `hosting-and-environments.md`
- Usher Route A/B and exit 7: `.agents/skills/yoke/usher/deploy.md`
- Merge-only `target_tier`: `docs/public/reference/db-reference/projects-and-flows.md`
- QA scopes and `command` vs `command-ci`: `qa_command_plan_registration.py`
- `ci_workflow_file` / `merge_queue` templates: `projects_seed_ci_workflow.py`
- Registered-command target matrix: `qa_command_plan_registration.py`
