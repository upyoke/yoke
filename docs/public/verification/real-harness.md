# Real harness Machine QA

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Real harness QA
<!-- /yoke:breadcrumbs -->

Real-harness QA runs the actual coding-agent CLI against a candidate on a registered Test Machine. Use it when hooks, session registration, or native tool decisions are part of the behavior being verified. Each harness starts from its own sealed golden baseline; signed-in harness credentials remain on that machine.

Follow the [host provisioning guide](test-machines/host-provisioning.md) before running a case. Windows runs native Linux CLI cases inside its registered WSL2 home. A missing login or GUI bridge is a prerequisite failure that needs the named recovery, rather than a product verdict.

A passing case needs the expected executor and workspace, native hook records, affirmative allow and deny decisions, and successful cleanup. Model prose, a completion marker, and a zero CLI exit do not prove the behavior alone. Missing telemetry is unavailable evidence.

Inspect the QA execution's transcript and `raw_result.preparation.evidence` before retrying preparation. Its `baseline_outcome` distinguishes a restore that never started, an attempted restore, and a completed restore. A planned scratch path exists only when `scratch_created` is true; preserve failure captures until host state is reconciled.

For project QA, use `yoke qa plan run --plan PLAN --project P`; read its `--help` for candidate and machine bindings.

Machine QA execution contracts carry `public_ref` and
`deployment_member_public_ref` for item subjects. The engine composes those
refs through the issuance transaction before sealing the case target and
execution digests; clients reject
internal item fields and incomplete refs.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
