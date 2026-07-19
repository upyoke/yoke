# Registry and OIDC Pack

Provides a container registry and separate GitHub Actions roles for
infrastructure changes and application delivery using short-lived OIDC tokens.

## Project-specific work

- Set the repository, registry name, AWS account, regions, branches, and GitHub
  environments.
- Narrow trust conditions and permissions to the project's real workflows.
- Apply the stack, then verify the published repository variables match its
  role outputs before removing any static credentials.
- Prove both infrastructure and delivery assumptions in live workflows.
- GitHub's built-in workflow token cannot read repository variables. A hosted
  Actions preview therefore needs a project-configured, repository-scoped App
  token broker; the Self-hosted Runners Pack provides one when that Pack is
  installed. Projects without that Pack can run the preview from a connected
  local operator or provide an equivalent broker before enabling the CI lane.

The infrastructure and delivery role outputs are the only supported GitHub
Actions role outputs. Projects upgrading from an earlier version may remove
the combined compatibility output after both repository variables and both
workflow paths have been proven.
