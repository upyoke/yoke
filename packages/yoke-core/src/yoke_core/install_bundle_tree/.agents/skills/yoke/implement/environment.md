# Implement — Ephemeral Environment Orchestration

The implementation-entry engine owns this capability-gated phase in one
Python process and emits `AdvancePhaseCompleted{phase="environment"}`.
This document is its outcome contract; agents do not repeat branch pushes,
environment writes or URL derivation by hand. Task-graph entry belongs to
Conduct's environment phase.

Capability presence is read through `projects.capability.has`; settings
through `projects.capability_settings.get`. The engine validates the
`ephemeral-env` policy using `ephemeral_policy_from_capability`.

| Outcome | Meaning and action |
|---|---|
| skipped:no-project | Item has no project |
| skipped:no-capability | No ephemeral-env capability; continue without preview |
| skipped:flow-triggered | Valid flow policy deploys later through its flow; no dead pending row |
| pending:policy-invalid | Malformed capability settings; repair with registered capability settings |
| pending:no-repo-root | No verified execution checkout; resolve the lane |
| pending:push-failed | Credentialed push of actual lane branch failed; advisory, no environment row created |
| pending:env-create-failed | Local environment create returned no valid row id; surface returned result |
| provisioned | Row, derived URL and available branch SHA recorded |

For `github-push`, the engine pushes the lane's actual branch with the
machine's stored GitHub credential, creates the item-bound environment,
derives its slug/URL through the shared substrate using capability
`preview_domain`, and resolves the SHA from that same checkout/branch.
It uses local authority or registered HTTPS relays according to the
connection; credentials remain capability-owned.

To repair policy, use `projects.capability_settings.merge` through:

```text
yoke projects capability-settings merge --project P --cap-type ephemeral-env --set KEY.PATH=VALUE
```

Read `--help` and the current settings before choosing the exact key/value.
A validated flow trigger is dispatched later by the workflow's owner;
entry does not create a pending preview or start its flow.

A provisioned row stays pending until the Browser phase verifies an actual
workflow run. Its stored SHA may become stale after implementation commits;
Browser execution must prove the current candidate before accepting evidence.
Keep authored QA method configuration intact: the Browser gate supplies the
current preview URL to `yoke qa case run --base-url`. Never rewrite a case
contract just because a URL became available.

Surface the returned URL, state and any advisory honestly. A pending result
does not prove a server exists or serves the candidate. Continue entry's
finalize phase; Browser proof remains required wherever the pinned contract
places it.
