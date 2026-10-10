# Self-hosted Runners Pack

Provides an isolated, disposable GitHub Actions runner fleet with broker,
registration, host lifecycle, network, IAM, and a routing-only smoke workflow.

## Project-specific work

- Choose architecture, instance type, capacity, idle lifetime, and labels.
- Configure the GitHub App or equivalent registration authority without placing
  private keys in Pack source or receipts.
- Review network egress, deployment SSH targets, IAM, and termination behavior.
- Exercise scale-up, parallel jobs, idle reaping, failed registration, and
  host replacement before relying on the fleet.
- Run `runner-fleet-smoke.yml` while the fleet is at zero and confirm it wakes
  a correctly labeled machine with the configured operating-system architecture.

## Architecture

Architecture accepts `arm64` or `aarch64` for ARM, and `x64`, `amd64`, or
`x86_64` for x86. Values are case-insensitive and surrounding whitespace is
ignored. Unsupported values refuse with `unsupported_runner_architecture`
before fleet resources are created. The AMI, host download, and broker
registration all use the normalized architecture.

## Stored instants and stopped-writer cutover

Lifecycle, per-host idle clocks, bootstrap and termination markers, job events,
and owned token expiry output use UTC RFC3339 strings with exactly six
fractional digits and `Z`. Missing idle clocks and `action=none` event times
are JSON null. Numeric epochs and noncanonical strings refuse with a named
runner instant recovery; the runtime never guesses historical formats.

The Lambda archives carry exact canonical `yoke_contracts` Python and Node
timestamp resources, so deployment needs no ambient contracts installation.
GitHub App JWT NumericDate claims remain provider-defined integer seconds;
queue-activity identifiers are opaque tokens and retain their bytes.

The component's `lifecycle_writers_paused` boolean stops webhook, bootstrap
broker and reaper through reserved concurrency zero. Normal concurrency is
5, 2 and 1 respectively. The capability setting is `lifecycle.writers_paused`
and the rendered Pulumi key is `webapp-infra:lifecycle_writers_paused`; its
value must match Yoke's digested authority intent before resources are created.
Adopt the matching Pulumi Foundation stack-config update alongside this Pack.
Follow [operations](operations.md) before resuming an existing fleet.

For existing fleets, `lifecycle.code_frozen=true` with paused writers renders
`lifecycle_code_frozen` and preserves exact deployed producer inputs in the
pause-only IaC step. After verified drain, clear the freeze while retaining
the pause to upgrade code. Resume only after SSM conversion/readback. False
controls leave ordinary authority envelopes unchanged; true controls require
explicit matching authority. See operations for the refresh/preview proof.
