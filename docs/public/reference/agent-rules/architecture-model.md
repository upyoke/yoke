# Architecture model

The rules file every session loads carries the short normative form of each rule. This document is the deep home the rules file points at: the same rules with the reasoning, the worked failure modes, the flag matrices, and the edge cases that decide close calls. Read the section you need before the action it governs — nothing here is optional background, it is simply longer than a startup channel can carry.

## Architecture model

Yoke encodes architectural taste as machine-checkable invariants on path targets, not style-guide prose. Every project may declare an `architecture_model` Project Structure family (singleton): the single policy document carrying the layer map, area patterns, dependency rules, cross-cutting gateways, exemption patterns, and the `package_roots` layout mapping module resolution reads — consumed by the architecture-fitness Doctor HCs, the status gate, the board's architecture section, and the workbench Architecture page. Setup is scan-derive-accept for every repo state: `yoke project-structure architecture-draft get --project P` proposes a draft from the tree (an empty repo yields the minimal vocabulary-only map), the operator reviews and edits, and `project_structure.patch.apply` writes it — identical for yoke and external projects. Coverage and violations come from one shared computer via `yoke project-structure architecture-health get --project P`.

### Layer vocabulary

```text
schema_storage -> payload_validators -> persistence_queries -> domain_invariants -> service_api -> orchestration -> harness_adapters -> skill_docs
```

Arrows mean *"may depend on"*. The payload expresses per-layer `may_depend_on` and `forbidden_edges` under a `layers` key (full schema in the architect's packet). Domain modules can't reach into orchestration, harness adapters, or skill/docs prose; service/API wrappers call domain invariants but don't re-implement them; orchestration coordinates without becoming source-of-truth; harness adapters use sanctioned service/session contracts; skill/docs prose teaches but never substitutes for enforced invariants.

### Domains

Domains group concerns by path patterns, and every pattern declares both facts at once: `domains[].path_roots` entries are `{glob, layer}` objects — the area (domain) and the kind (layer) of the files the glob matches, finer patterns where an area mixes kinds, first match wins (`*` stays inside a path segment; `**` crosses). Classification is derived, never inferred: every `project.snapshot.sync` converges per-file `path_context_values` rows with the map (`architecture_layer` / `architecture_domain`), so labels refresh whenever the file inventory does. Operator-authored override rows — any architecture-family row whose value carries no `glob` key — survive every refresh. Read the authoritative mapping from the payload, not this prose.

### Cross-cutting entrypoints

Cross-cutting concerns enter through sanctioned interfaces, not ambient reach-around imports. The payload's `cross_cutting_entrypoints` registry names the approved gateway modules per concern — commonly `backlog_mutation`, `session_identity`, `events`, `path_authority`, `live_operation_ownership`, and `external_artifact_fetch`. One-hop import allowlists cannot express compositional defect classes; those live as project-local checks (the DB-connection guard is the worked example), and retired entrypoints record their rationale in the payload's `decisions` list. Read the approved gateways from your project's model payload rather than this prose.

The `guarded_imports` field on each entrypoint names symbols whose direct import outside the approved list fires `HC-architecture-cross-cutting-entrypoint`. Consult the entrypoint metadata rather than copying gateway symbols into prose.

### Exemption families

Generated artifacts, fixtures, archive surfaces, test files, and separately versioned Pack source inherit exemption context families from `path_context_values` rather than from prose allowlists — `architecture_generated`, `architecture_fixture`, `architecture_archive`, `architecture_test_surface`, `architecture_pack_source`. The map's optional `exemptions` list (`{glob, family}` entries, matched before domain patterns) seeds these rows on every snapshot sync, so `HC-architecture-unclassified-path` PASSes without per-file operator action.

### Item-level architecture impact

Every item declares an `architecture_impact` classification at idea / refine time. The closed enum:

| Value                       | Meaning                                                                       |
|---                          |---                                                                            |
| `none`                      | No effect on dependency shape, path classification, or cross-cutting entries. |
| `path_context_only`         | Touches inherited path-context families; does not change the model payload.   |
| `architecture_model_change` | Modifies the architecture model itself (domains, layers, edges, entrypoints). |
| `uncertain`                 | Declared at idea time; refine / Architect must resolve before refined-idea.   |

`architecture_impact='uncertain'` blocks `refining-idea → refined-idea` via the readiness check; the authoritative status gate is defense-in-depth for the same rule across every later transition.

### Doctor surface

Six HCs enforce the model: `HC-architecture-unclassified-path`, `HC-architecture-forbidden-edge`, `HC-architecture-cross-cutting-entrypoint`, `HC-architecture-impact-declaration`, `HC-architecture-scan-error`, and `HC-architecture-model-doc-drift`. The three snapshot checks fold the same shared health computer the board section and Architecture page read, record at WARN (promotion to FAIL waits until classifications prove stable), self-skip cleanly on minimal-schema fixtures, and emit findings keyed to canonical path targets so violations are always attributable.
