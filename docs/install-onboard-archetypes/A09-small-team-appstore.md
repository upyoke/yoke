# A09 — Jules, small team, iOS/Android app store, macOS, GitHub + CI

**Vector:** small team · active · hosting none (mobile) · macOS · GitHub with
CI · **app store**.

Jules ships TestFlight / Play Console from GitHub Actions (`fastlane`). There
is no HTTPS product environment. They want Yoke for backlog items and agent coding,
not a web deploy.

## Fit / break / gaps

| | |
|---|---|
| Fits | macOS install. Existing Xcode/Android repo. GitHub App. Skip hosting and confirm merge-only delivery. |
| Breaks | No Yoke web environment is proposed. TestFlight/Play remains an external runner rather than a Yoke deployment flow. |
| Gaps | A named TestFlight/Play runner is still absent; merge-only correctly covers Yoke's local delivery boundary. |

## Transcript — installer + wizard

Darwin. uv present. This machine. Connect GitHub (repo `studio/ios-app`).
Existing folder `~/src/ios-app`. Use connected repo. Prefix `IOS`. Skip
hosting (no AWS website). Apply.

Hand-off: Claude/Codex; they use Cursor.

## Transcript — `/yoke onboard`

Survey: `fastlane/`, `.github/workflows/testflight.yml`, no Dockerfile web
service. Strategy: ship iOS. The profile maps the existing app, omits AWS
Packs, `aws-admin`, web environments, and a domain, then offers merge-only or
no default. The team confirms **merge-only**: local merge with no environment
or Yoke deployment pipeline.

Step 5 creates an active empty-tier flow and verifies it as the project
default. Idea attaches that flow to seeded work. Usher recognizes the empty
target tier semantically and takes Route A (`--skip-deploy`) without creating
a deployment run; TestFlight remains in the external Actions workflow.

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
| Deployment flow | Profile delivery; merge-only `target_tier` NULL | Idea assigns the default; Usher Route A creates no run | External TestFlight remains Actions |
| Domain | Step 6 default subdomain | Skip `domain-setup=not-needed` | No hostname |

Ledger: G-app-store-deploy, G-test-setup-unasked, G-ci-workflow-undeclared, G-command-ci-misbind, G-legacy-suite-unmapped, G-qa-plan-needs-env.
