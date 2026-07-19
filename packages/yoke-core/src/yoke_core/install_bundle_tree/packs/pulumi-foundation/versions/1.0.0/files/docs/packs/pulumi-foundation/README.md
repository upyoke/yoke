# Pulumi Foundation Pack

Provides the shared Pulumi project entrypoint, stack composition, aliases,
repository provider, and immutable stack-file generators used by other Packs.

## Project-specific work

- Choose the state backend, KMS provider, stack names, environments, and stable
  deployment namespace.
- Declare only the infrastructure components the project actually uses.
- Import existing resources and preserve operator-owned stack metadata.
- Review every preview before applying and require a clean refresh preview
  afterward.
- Document project-specific infrastructure recovery in the project repository.
