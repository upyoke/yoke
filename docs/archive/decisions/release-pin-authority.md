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
3. The outer release bridge records that successful deployment through
   `yoke release-pin record --project platform --environment <target> --pin
   <version>`. The Platform-scoped `deployment_ci` identity may use only this
   capability-routed mutation; the infrastructure identity stays read-only
   and neither identity receives generic project-settings administration. The
   outer job remains failed until the record command returns a non-empty
   receipt; Platform's inner promotion contains no control-plane writer.
4. Promotion's materialization push is a commit the release itself wrote,
   and it lands in the range the *next* release's composition validation
   reads. Nothing else can attribute it, so the bridge records it against the
   run that produced it — `yoke deployment-runs release-output record
   <run-id> --project platform` — immediately after the pin receipt. The
   commit is resolved server-side from the branch that run already bound, so
   no repository ref is named in the workflow. Skip this and every following
   release refuses to compose until somebody records a
   `composition_resolution` by hand.

   That call is made from a CI runner, which has no harness session and holds
   only a scoped project token, so the write declares both facts explicitly:
   `ambient_session_required=False`, and a by-id authorization carve-out out
   of the `deployment_runs.*` org-admin prefix onto its own narrow
   `deployment_runs.release_output.record` permission — the same shape
   `release_pin.record` uses, and for the same reason. That permission is
   granted to the `deployment_ci` role and to the project owner, and to
   nothing else; the release identity still reaches no other
   `deployment_runs.*` write. Both halves are required: the session opt-out
   without the carve-out leaves the bridge refused, which is exactly how the
   first attempt shipped.

   A third fact is easy to miss and refused the second attempt: these two
   writes authorize against *different projects*. The pin receipt writes
   Platform's environment settings, so it authorizes against Platform and is
   correctly made under the scoped Platform identity. The release-output
   write's data is the deployment run, which belongs to Yoke, so it
   authorizes against Yoke and needs Yoke's release identity — the Platform
   token holds `deployment_ci` on Platform only, by design. The bridge
   therefore restores Yoke authority between the two, and `--project
   platform` on the record command names whose *source* holds the commit,
   never the project the write authorizes against.
5. `yoke release-pin verify` compares the desired-pin leaf to the
   environment's configured health probe without deploying. Platform owns the
   two verification coordinates in its capability: `probe_url_path` is
   `release.health_probe_url`, and `served_pin_response_path` is
   `engine_version`. Disagreement is a doctor/operator signal, not silent
   drift.

Platform's project owner installs those coordinates through the ordinary
project-owned capability surface:

```bash
yoke projects capability-settings merge --project platform \
  --cap-type release_pin \
  --set probe_url_path=release.health_probe_url \
  --set served_pin_response_path=engine_version
```

Both assignments travel in one validated merge. This is an explicit Platform
configuration update, not a global migration or a fallback embedded in Yoke;
other projects choose their own settings and response paths.

## Host fixes without cherry-pick divergence

Parity merges of `main` into `stage` regenerate pin sites through
`python3 ops/release_pin.py merge-main` instead of text-merging them.
Promotion runs that composition before a Stage pin advance. Do not
cherry-pick pin commits between environment branches; that is what left
identical content on divergent histories.

## Related

- Platform runbook: `docs/runbooks/deploy.md` (Platform repo)
- Capability declaration: project `release_pin` settings
  (`pin_file`, `branch_by_environment`, `environment_by_target`, and the
  explicit `desired_pin_path`, `probe_url_path`, and
  `served_pin_response_path`). Generic Yoke machinery contains no Platform
  environment id, settings leaf, or probe-response path and does not synthesize
  missing config.
