# Architecture model

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Architecture model
<!-- /yoke:breadcrumbs -->

Read the authoritative `architecture_model` Project Structure payload: layers, domains,
dependency rules, gateways and exemptions.

- Read: `yoke project-structure get --project yoke --family architecture_model`.
- Draft: `yoke project-structure architecture-draft get --project P`. The operator reviews it;
  `project_structure.patch.apply` writes it.
- Health: `yoke project-structure architecture-health get --project P`.
- Layers may depend only on what `may_depend_on` allows:

```text
schema_storage -> payload_validators -> persistence_queries -> domain_invariants ->
service_api -> orchestration -> harness_adapters -> skill_docs
```

- Cross-cutting concerns use only gateways in `cross_cutting_entrypoints`;
  importing a `guarded_imports` symbol elsewhere fires `HC-architecture-cross-cutting-entrypoint`.
- Generated, fixture, archive, test and Pack-source exemptions use the map's
  `exemptions`, not prose allowlists.

## Item architecture impact

Declare `architecture_impact`: `none`, `path_context_only`,
`architecture_model_change` or `uncertain`. Refine or Architect must resolve `uncertain`; it
blocks `refining-idea → refined-idea`.

## Related

- [Operating with agents](../index.md)
- [Agent operation homes](index.md)
