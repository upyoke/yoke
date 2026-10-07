# Real harness Machine QA

This source-maintainer procedure is documented in the [upstream source guide](https://github.com/upyoke/yoke/blob/main/docs/testing-verification/real-harness.md).

For project QA, use `yoke qa plan run --plan PLAN --project P`; read its `--help` for candidate and machine bindings.

Machine QA execution contracts carry `public_ref` and
`deployment_member_public_ref` for item subjects. The engine composes those
refs through the issuance transaction before sealing the case target and
execution digests; clients reject
internal item fields and incomplete refs.
