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
- A GitHub Actions workflow that previews this Pack with its ephemeral
  repository token must grant `actions: write`; the GitHub provider reads the
  repository variables during refresh and applies updates through the same
  token. Keep `contents: read` and `id-token: write` alongside that permission.

The infrastructure and delivery role outputs are the only supported GitHub
Actions role outputs. Projects upgrading from an earlier version may remove
the combined compatibility output after both repository variables and both
workflow paths have been proven.
