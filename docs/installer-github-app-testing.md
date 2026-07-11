# Installer GitHub App Live Testing

This companion to [Installer Testing](INSTALLER-TESTING.md) defines the live
GitHub App execution boundary. The canonical scenario rows are in that guide's
Wave 5 table so the campaign parser includes them in manifests and assignments.

Only `GITHUB-001` and `PUBLISH-001` currently have deterministic coordinator
recipes. `GITHUB-002` through `GITHUB-024`, `PUBLISH-002` through `PUBLISH-013`,
`PROJECT-SOURCE-006`, `PROJECT-META-008`, `APPLY-005`, `APPLY-008`, `STATE-002`,
and `STATE-007` require an operator-attended run against a real GitHub App. A
blocked recipe stub is not a pass and must not be reported as automated proof.
Retain terminal captures, browser screenshots where allowed, post-apply state,
and a secret scan for every manual result.

## Evidence boundary

- `GITHUB-001` proves only the backlog-only branch. It says nothing about
  browser authorization, App installation, or repository automation.
- `GITHUB-002` through `GITHUB-016`, plus `GITHUB-020` through `GITHUB-024`,
  require both screen evidence and post-apply
  machine/control-plane state. A green screen without the expected credential,
  installation, or binding state is a failure.
- `GITHUB-017` through `GITHUB-019` require an observed successful GitHub API
  outcome in addition to Yoke state. A mocked bearer transport or a skipped
  mutation is not live proof.
- Disconnect evidence must distinguish local user authorization from the
  GitHub-managed App installation and project repo binding; they are separate
  layers with separate removal operations.
