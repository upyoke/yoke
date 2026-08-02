# Pulumi Foundation Pack

Provides the shared Pulumi project entrypoint, configuration helpers, resource
aliases, and GitHub repository provider used by infrastructure Packs.

## Project-specific work

- Choose the state backend, KMS provider, stack names, environments, and stable
  deployment namespace.
- Install only the infrastructure component Packs the project actually uses.
- Import existing resources and preserve operator-owned stack metadata.
- Review every preview before applying and require a clean refresh preview
  afterward.
- Document project-specific infrastructure recovery in the project repository.
