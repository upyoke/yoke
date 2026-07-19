# Deploy Runbook: Yoke

How Yoke gets deployed, for humans and agents working in this repo.
Yoke's authoritative DB owns deploy execution (flows, capabilities,
environment settings); this file carries the context those records cannot:
the why, the order, the gotchas.

## Targets and environments

- Stage is served at `https://app.stage.upyoke.com` with its API and public
  installer at `https://api.stage.upyoke.com`.
- Production is served at `https://app.upyoke.com` with its API, package index,
  and public installer at `https://api.upyoke.com`.
- Stage and Production are independent targets. Neither environment's release
  is evidence that the other one deployed.
- Platform owns the hosted promotion boundary. Yoke supplies the exact source,
  wheel, and server-image identities that Platform deploys.

## Build and release

`platform-release-bridge.yml` allocates the next immutable annotated
`vX.Y.Z+launch.N` tag for the requested Yoke commit. That tag independently
starts the wheel and server-image factories. The wheel factory builds, checks,
signs, and publishes the four lockstep Yoke packages; the image factory builds,
signs, and publishes the exact multi-architecture server image. Platform then
promotes those exact artifacts to the requested environment.

Release tags, GitHub Releases, package-index release directories, and image
digests are immutable. Never hand-create or move a release tag, hand-edit a
Platform Yoke pin, or dispatch a component deploy as the normal path. See
`docs/releases/README.md` for artifact and provenance checks.

## Deploy procedure

Use the project-owned definitions in `.yoke/deployment-flows.json`:

- `yoke-hosted-stage-no-ci-gate` for Stage;
- `yoke-hosted-production-hotfix-no-ci-gate` for an attended Production
  hotfix; and
- the item-assigned hosted Production flow for normal item-bound delivery.

Item-bound delivery normally runs through `/yoke usher YOK-N`. For an attended
environment release, push the intended commit to `main`, merge that exact
content to `stage`, create one recorded zero-member run for each target, and
execute both independently through the Production control-plane admin
environment. Each flow sends a unique `yoke_dispatch_id` and disables
head-SHA reuse, so every run receives its own GitHub Actions receipt.

Do not make Stage finish before starting Production: the two trains are
independent. A run that must not execute is marked `cancelled`; deployment
history is never deleted or rewritten.

## Verification

A release is green only after the release bridge, wheel factory, server-image
factory, and target Platform promoter all succeed and the Yoke deployment run
is complete. Then verify:

- `yoke --env stage status` and `yoke --env prod status` reach their intended
  environments and report the expected release;
- the target hosted app loads and an authenticated organization page works;
- the target's exact package index (`https://api.stage.upyoke.com/simple/` or
  `https://api.upyoke.com/simple/`) exposes the published Yoke packages; and
- any changed UI surface is exercised in the browser against each environment
  where it was released.

An HTTP 200 from the web shell alone is not enough: the recorded run and exact
artifact/promotion receipts are part of the release proof.

## Rollback

Redeploy the last known-good immutable Yoke wheel and server-image identities
through Platform's normal target flow. Never move the bad release tag or
overwrite its artifacts.

Before rollback, determine whether the release applied a forward-only database
migration or accepted writes that the older engine cannot read. If so, use the
governed database recovery path in `recovery.md` and the Platform recovery
runbook; a code rollback alone is not safe. The core-container deployer may make
one bounded automatic swap back to the prior healthy image, but that restores
availability only—the failed deployment run remains failed and must be
investigated.
