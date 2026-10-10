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

Confirm XCTest/Gradle argv, scheme/destination and required simulator/device. Bind the Actions test workflow separately from TestFlight/store upload. Registered quick/full commands use a project target and need no HTTPS environment. Deployed scopes require their declared target contract; do not create a web environment for app-store verification.

The confirmed profile, command/CI binding and immutable QA attachment follow
[test-setup.md](test-setup.md); this example is not a live setup receipt.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Web environment | Profile environments box | Do not `environment create` for stage/prod | No site rows |
| Deployment flow | Profile delivery; merge-only `target_tier` NULL | Idea assigns the default; Usher Route A creates no run | External TestFlight remains Actions |
| Domain | Step 6 default subdomain | Skip `domain-setup=not-needed` | No hostname |

Ledger: G-app-store-deploy.
