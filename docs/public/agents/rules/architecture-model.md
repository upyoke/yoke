# Architecture model

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Architecture model
<!-- /yoke:breadcrumbs -->

## Architecture model

A project's `architecture_model` Project Structure family holds its layers, domains, dependency
rules, cross-cutting gateways and exemptions. The payload is the authority; read it, not prose.

- Draft: `yoke project-structure architecture-draft get --project P`. The operator reviews it;
  `project_structure.patch.apply` writes it.
- Health: `yoke project-structure architecture-health get --project P`.
- A layer may depend only on what its `may_depend_on` allows. Layer vocabulary:

```text
schema_storage -> payload_validators -> persistence_queries -> domain_invariants ->
service_api -> orchestration -> harness_adapters -> skill_docs
```

- Cross-cutting concerns enter only through the gateways in `cross_cutting_entrypoints`;
  importing a `guarded_imports` symbol elsewhere fires `HC-architecture-cross-cutting-entrypoint`.
- Generated, fixture, archive, test and Pack-source paths are exempt through the map's
  `exemptions` list, not prose allowlists.

## Item architecture impact

Each item declares `architecture_impact`: `none`, `path_context_only`,
`architecture_model_change` or `uncertain`. Refine or Architect must resolve `uncertain`; it
blocks `refining-idea → refined-idea`.

## Related

- [Operating with agents](../index.md)
- [Agent operation homes](index.md)
