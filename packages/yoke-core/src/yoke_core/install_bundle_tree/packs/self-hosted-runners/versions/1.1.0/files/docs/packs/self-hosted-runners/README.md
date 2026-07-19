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
