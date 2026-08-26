# A09 — Jules, small team, iOS/Android app store, macOS, GitHub + CI

**Vector:** small team · active · hosting none (mobile) · macOS · GitHub with
CI · **app store**.

Jules ships TestFlight / Play Console from GitHub Actions (`fastlane`). There
is no HTTPS product environment. They want Yoke for tickets and agent coding,
not a web deploy.

## Fit / break / gaps

| | |
|---|---|
| Fits | macOS install. Existing Xcode/Android repo. GitHub App. Skip hosting. |
| Breaks | Execution profile "environments stage + prod" and default **web** subdomain. `production-deploy` / Pulumi Packs are web/AWS shaped. No TestFlight/Play runner. |
| Gaps | App-store delivery as merge-only or a named external store flow. `target_tier` NULL merge-only exists in schema and is not offered. |

## Transcript — installer + wizard

Darwin. uv present. This machine. Connect GitHub (repo `studio/ios-app`).
Existing folder `~/src/ios-app`. Use connected repo. Prefix `IOS`. Skip
hosting (no AWS website). Apply.

Hand-off: Claude/Codex; they use Cursor.

## Transcript — `/yoke onboard`

Survey: `fastlane/`, `.github/workflows/testflight.yml`, no Dockerfile web
service. Strategy: ship iOS. Profile proposal still:

- Packs: `webapp-scaffold` (wrong — existing app maps `not-needed` if they
  notice), `pulumi-foundation`, `vps-hosting`, `registry-oidc`,
  `production-deploy`
- Capabilities: `aws-admin`
- Environments: stage + prod
- Domain: `{slug}.{default_domain}`

**User must** delete hosting/domain/deploy Packs at confirmation. If they
accept the template, step 5 creates persistent flows to web environments they
do not have; step 7 asks to apply AWS infra for a mobile app.

Correct confirmation: no scaffold, no aws-admin, no environments, no domain
merge. `yoke project-structure deploy-defaults get` empty. Seeded items omit
`--deployment-flow`.

Usher: Route A (`--skip-deploy`). Exit 7 only if a real flow was assigned.

CI: Actions exist → project may declare `ci_workflow_file`. That is GitHub
CI for tests/signing, not Yoke `core-container-deploy`.

## Test setup

**Reality:** XCTest / Gradle + `fastlane` + `.github/workflows/testflight.yml`.
Not a web pytest tree. Simulator or device needed.

**Bind today:** `ci_workflow_file` can name the **test** workflow (not
TestFlight). Local `command` is `xcodebuild` / `fastlane test` on macOS.
`e2e`/`smoke` stay local unless `scope_workflows` says otherwise. No
HTTPS env → `yoke qa plan create --environment` has nothing honest to
name.

**Onboard:** survey sees `fastlane/` and does not register XCTest.

**Ask that should happen:** which Actions file is unit/UI tests vs store
upload; register that as `quick`. Refuse binding `command-ci` to
`testflight.yml` if that job ships a build.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Web environment | Profile environments box | Do not `environment create` for stage/prod | No site rows |
| Deployment flow | Profile delivery; merge-only `target_tier` NULL | Usher Route A; idea omits `--deployment-flow` | External TestFlight remains Actions |
| Domain | Step 6 default subdomain | Skip `domain-setup=not-needed` | No hostname |

Ledger: G-app-store-deploy, G-no-deploy-default-flow, G-execution-profile-no-hosting-still-envs, G-test-setup-unasked, G-ci-workflow-undeclared, G-command-ci-misbind, G-legacy-suite-unmapped, G-qa-plan-needs-env.
