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
| G-no-merge-only-default | blocker | deployed / merged | Merge-only flows (`target_tier` NULL) exist; onboard never offers them; idea always stamps `deploy-defaults get` | A01 A09 A12 + all no-host | YOK-2467 |
| G-forge-github-only | missing-config-surface | merged | Skip GitHub works; GitLab/Bitbucket cannot bind, clone-list, or merge-queue | A06 A11 | YOK-2469 |
| G-handoff-cursor | missing-teaching | installed | Shim hand-off: "open Claude Code or Codex" then `/yoke onboard` | A01 A03 A05 A09 | YOK-2468 |
| G-app-store | missing-config-surface | deployed | No TestFlight/Play/`fastlane` runner; profile is web stage+prod | A09 | YOK-2470 |
| G-selfhost-not-in-wizard | friction | installed | Team server asks URL+token; `yoke self-host init` is a separate doc | A06 A07 | YOK-2471 |
| G-migration-undeclared | missing-config-surface | migrated | No onboard question for `migration_model` / "no DB to migrate" | A03 A06 A07 | YOK-2472 |
| G-byo-aws-identity | missing-config-surface | deployed | Hosting collects a new IAM user access key pair only | A03 A07 | YOK-2473 |
| G-idea-default-flow | blocker | released | `infer-and-create.md`: non-empty deploy-defaults **always** assigned | all with a default flow | YOK-2474 |

## Declare / refuse / instead (crux)

### Deployment, environment, release

**Declare:** execution profile must record one of: persistent env + flow;
merge-only flow; or **no flow**. Hosting deferred ⇒ last two only.

**Refuse:** Usher Route B / `deployment-runs start-for-item` when no
environment exists. Idea must not pass `--deployment-flow` when defaults are
empty. If a persistent flow is set and `--skip-deploy` is used: exit 7
(`usher/deploy.md`) — that refusal is correct **if** the flow was intentional.

**Instead:** Route A `yoke watch merge done-transition -- PREFIX-N --skip-deploy`
for empty/`-internal` flow. Seed-work already omits `--deployment-flow` when
`deploy-defaults get` prints nothing.

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
