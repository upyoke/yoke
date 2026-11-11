# Pulumi Foundation Pack

Provides the shared Pulumi project entrypoint, resource aliases, and GitHub
repository provider used by infrastructure Packs. See `stacks.md` for the
stack file each project checks in and the values Yoke adds when it runs one.

## Project-specific work

- Choose the state backend, KMS provider, stack names, environments, and stable
  deployment namespace.
- Check in one `infra/Pulumi.<stack>.yaml` per stack holding the project's
  own values (see `stacks.md`).
- Install only the infrastructure component Packs the project actually uses.
- Import existing resources and preserve operator-owned stack metadata.
- Review every preview before applying and require a clean refresh preview
  afterward.
- Document project-specific infrastructure recovery in the project repository.
