# Migration Model Fleet — What a Release Must Rehearse

A history entry that applies cleanly to the model's validation surface proves
nothing about the live databases behind it, because that surface is current
and a current database has nothing pending. Before a release carries an
entry, a throwaway copy of every live database the model owns is converged
through that model's real boot sequence. Each model in a project's
`migration_model` capability declares what that means for it, under `fleet`.
There is one preflight and one release gate for every project; the
declaration is the only per-project part.

## Declaration

| `fleet.kind` | Databases rehearsed | Boot sequence | Other keys |
|---|---|---|---|
| `engine_tenants` | The engine's tenant databases on the environment's admin cluster, rostered with the reason each candidate is or is not a member | The engine's boot-time schema and history convergence | none |
| `named_databases` | `names`: databases on the environment's admin cluster | `converge_argv`, run from the project checkout with the copy's DSN bound to `runner.config.connection_env_var`; optional `verify_argv` runs the same way afterwards and must exit 0 | `schema_shape_sources`: checkout-relative files whose content is the schema the boot converges |
| `none` | Nothing | Nothing | `reason`: why this model has no live databases a release can rehearse |

```jsonc
// The engine's own model.
"fleet": {"kind": "engine_tenants"}

// A service converging its own registry database at boot.
"fleet": {
  "kind": "named_databases",
  "names": ["service_registry"],
  "converge_argv": ["uv", "run", "--project", "services/svc", "python", "-m", "svc.schema", "init"],
  "verify_argv": ["uv", "run", "--project", "services/svc", "python", "-m", "svc.schema", "status"],
  "schema_shape_sources": ["services/svc/src/svc/schema.py"]
}

// One database on a host the admin cluster cannot copy.
"fleet": {"kind": "none", "reason": "single SQLite database on the production host"}
```

`fleet` is optional to the capability validator, so existing documents stay
valid, but a release gate refuses a model that declares none: an undeclared
fleet and an empty one are different facts. Declare it with
`yoke projects capability-settings merge --project P --cap-type migration_model`.

The admin cluster is the environment's `release.admin_connection` setting on
the project's own environment. A `named_databases` fleet runs from the
project's checkout registered on this machine (`yoke project register`), so
the declared commands find the code they converge with. A non-Python schema
source is digested byte for byte; a Python one by its syntax tree, so comments
and docstrings do not invalidate coverage.

## Preflight

```bash
yoke watch preflight -- --project P [--model M] <environment> [db ...] \
    --record-receipt --product-sha SHA --receipt-env <control-plane>
```

`--model` defaults to the capability's `default_model`. The live databases are
only read: each is dumped, restored into the local embedded cluster, converged,
verified, and dropped. A passing run with `--record-receipt` writes the
covered history entry names and the schema-shape digest onto that project
environment's own settings document under `release.fleet_rehearsal`, on the
prod release-gate control plane. Coverage is the union of passing runs and
never ages out; one environment's receipt never satisfies another.

## Release gate

Before a deployment run dispatches a GitHub workflow for a project that
declares a `migration_model`, it reads every model's fleet. A `none` fleet is
skipped with its reason printed. An undeclared fleet refuses the dispatch with
the declaration recipe. Otherwise the gate reads the release commit's history
entries (from the model's `runner.config.modules_dir`) and schema-shape digest,
and when the target environment's receipts do not cover both it runs the
preflight for that model before dispatching, then re-reads coverage and
refuses if the receipt still falls short.

## Item rehearsal is a different receipt

`yoke migration rehearse PREFIX-N` proves the item's entry against the
validation surface and writes its receipt to `migration_audit` on the control
plane that holds the item, where the `implementing -> reviewing-implementation`
gate reads it. Fleet coverage is release evidence and lives on environment
settings. Neither substitutes for the other.
