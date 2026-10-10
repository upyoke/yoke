# Test setup for onboarding examples

Source-maintainer reference: these archetypes illustrate setup choices. They
are not receipts for live installations. Current authority is the confirmed
profile and registered binding, not a transcript's past missing-feature claim.

The setup wizard covers PATH, destination, GitHub, project and hosting; test
posture belongs to harness onboarding. Follow
[profile confirmation](../../.agents/skills/yoke/onboard/profile-and-scaffold.md),
[verification binding](../../.agents/skills/yoke/onboard/verification-binding.md)
and [work seeding](../../.agents/skills/yoke/onboard/seed-work.md) when acting.

## Confirm the posture

Every project chooses explicitly; an undecided posture blocks completion:

- Survey a runnable suite: retain exact argv, roots, prerequisites and a
  documented reliable quick slice; full may be a distinct aggregate.
- Scaffold a minimal project-native suite when absent. Map existing files
  rather than overwrite them. Bind only after the scaffold applies.
- Keep materially flaky or known-red suites review-only: blocking
  `implementation_review` plus non-blocking exact legacy-command evidence.
- Attest no-tests only with the operator's required reason. Offer scaffold
  first; business model, SOW and future hosting do not choose the answer.

## Bind the actual gate

| Surface | Contract |
|---|---|
| `test_roots` | Path selectors for impacted selection; one keyed entry per tree |
| `verification_profiles.test_command` | Descriptive policy; does not bind QA |
| `registered-command-{scope}` | Registered plan, case, runner, target and attachments |
| `ci_workflow_file` | Eligible Actions **test** workflow under `.github/workflows/`; optional scope routing |
| `merge_queue` | GitHub plus declared test workflow and `merge_group` support |
| Item QA attachment | Immutable plan snapshot at the required pinned transition |

Register the confirmed command through the existing surface:

```text
yoke qa registered-command set --project P --scope SCOPE --command ARGV
```

Read its `--help` for target and routing options before binding.
`quick`/`full` carry project targets; no placeholder stage/prod is needed.
Local `e2e`/`smoke` choose exactly one declared environment or
`--requires-base-url`; CI deployed scopes require a declared environment.
Generic `qa plan create` requires an environment and is not the project-targeted
registered-command adapter.

Quick/full route through configured eligible CI, otherwise local `command`.
Deployed scopes default local unless explicitly scope-routed. Unreachable
`command-ci` refuses with a named reason; do not silently downgrade.
Jenkins, GitLab CI, Bitbucket Pipelines and a store-upload/deploy workflow are
not Actions test bindings. Eligible CI needs `workflow_dispatch` and
`yoke_dispatch_id`; queue verification also needs its PR/merge-group triggers.
Inspect the configured declaration and the source-backed Doctor result rather
than infer eligibility from a filename.

The scaffold Pack installs examples but does not itself register the gate.
Onboarding binds from the confirmed profile after apply and records
`verification-command-binding` evidence. Plan attachments must also respect
the item's pinned verification posture; see the binding owner for optional
selection and seeding recipes.

## No-tests lifecycle

The durable `verification_posture` declaration stores `attested-no-tests`
and the operator's reason:

```text
yoke qa no-tests attest --project P --reason TEXT
yoke qa no-tests clear --project P --reason TEXT
```

Read each command's `--help` before changing posture. Attestation retires
registered-command plans and supplies blocking implementation review at the
verification transition. It cannot coexist with registered commands; clear
returns the project to undecided before a new suite can be bound. Never invent
pytest, attest an existing failing suite as absent, or treat no command as an
empty gate. Path-shaped missing argv refuses; a bare tool unavailable on the
registering laptop is reported because its declared CI may provide it.

## Fit by suite

| Reality | Preserve in the profile |
|---|---|
| Maven/JUnit or PHPUnit | Actual unit/aggregate argv and each module's roots |
| XCTest/Gradle | Scheme, destination, simulator/device and test/upload separation |
| Containerized | Exact container invocation and prerequisites |
| Monorepo | Reliable quick slice, aggregate full and separate test trees |
| Known-red/flaky | Review-only plus advisory executable evidence |
| Empty/content-only | Minimal scaffold offer or operator-attested no-tests |

External CI, native Windows, other forges and unsupported hosts retain their
named limits. A valid local test binding does not imply support for their
deployment or remote merge automation.
