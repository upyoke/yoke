# Architecture model

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Architecture model
<!-- /yoke:breadcrumbs -->

Read the authoritative `architecture_model` Project Structure payload: layers, domains,
dependency rules, gateways and exemptions.

- Read: `yoke project-structure get --project yoke --family architecture_model`.
- Draft: `yoke project-structure architecture-draft get --project P`. The operator reviews it;
  `project_structure.patch.apply` writes it. Mixed directories use compact filename-hint
  globs in classification order (docs, storage, interface, then the directory default);
  the first matching pattern wins. Human reads group hint globs by parent directory;
  JSON retains the complete map for patch application.
- Health: `yoke project-structure architecture-health get --project P`.
- Layers may depend only on what `may_depend_on` allows:

```text
schema_storage <-> payload_validators (shared base pair)
persistence_queries -> migrations -> domain_invariants -> service_api ->
orchestration -> harness_adapters -> skill_docs
```

- The order shows layers, not permission to depend on every earlier layer.
  Every layer may use `payload_validators`; all other dependencies must be explicit.
  `schema_storage` holds table definitions. `migrations` may use only
  `schema_storage`, `persistence_queries` and `payload_validators`; imports of live
  domain code remain findings. `orchestration` may use storage and migrations.
- Domains are classification labels only; no check reads them as dependency
  boundaries. Each file gets one domain and layer from the first matching path
  pattern in declaration order. Put specific patterns before broader ones.
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
