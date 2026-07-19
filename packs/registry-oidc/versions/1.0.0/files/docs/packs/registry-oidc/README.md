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
