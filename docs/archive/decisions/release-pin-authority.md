# Release pin authority

## Decision

Stage and production keep separate Platform environment branches
(`stage` and `main`). The Yoke engine version pin does **not** live as
authority in those per-branch file copies. Desired pin authority is the
control-plane leaf `environments.settings.release.yoke_pin` on the
Platform environments `yoke-api-stage` and `yoke-api-prod`. Both
environments' tooling reads that schema. The committed
`yoke-release-pin.txt` (plus service requirements and lock) on each
environment branch remains a **build materialization** so Docker, uv, and
Actions can resolve wheels from an exact Platform SHA.

## Why separate branches stay

Stage and production must point at different public releases at the same
time, and each uses a different release index
(`api.stage.upyoke.com` vs `api.upyoke.com`). A branch is still the right
carrier for Platform host code and for the env-local index that the
materialized lock binds to. Collapsing to one branch would force another
store for host divergence and for index identity; it would not remove the
need for per-environment pin values.

What the dual pin-file copies got wrong was treating the branch-owned
file as the place that *defines* the desired release. That made a failed
promotion leave the dangerous half advanced, and it made a shared host
fix look like a pin merge conflict.

## Advance, failure, and agreement

1. Promotion still materializes and pushes pin sites onto the environment
   branch so the deploy SHA is self-describing for builds.
2. When the deploy train fails after that push, promotion restores the
   previous pin materialization on the same branch. The desired-pin leaf
   in the control plane is updated only after a successful deploy.
3. `yoke release-pin verify` compares the desired-pin leaf to the
   environment's configured health probe (`release.health_probe_url`)
   without deploying. Disagreement is a doctor/operator signal, not a
   silent drift.

## Host fixes without cherry-pick divergence

Parity merges of `main` into `stage` regenerate pin sites through
`python3 ops/release_pin.py merge-main` instead of text-merging them.
Promotion runs that composition before a Stage pin advance. Do not
cherry-pick pin commits between environment branches; that is what left
identical content on divergent histories.

## Related

- Platform runbook: `docs/runbooks/deploy.md` (Platform repo)
- Capability declaration: project `release_pin` settings
  (`pin_file`, `branch_by_environment`, `environment_by_target`)
