# Migration Model Fleet — What a Release Must Rehearse

A history entry that applies cleanly to the model's validation surface proves
nothing about the live databases behind it, because that surface is current
and a current database has nothing pending. Before a release carries an
entry, a throwaway copy of every live database the model owns is converged
through that model's real boot sequence. Each model in a project's
`migration_model` capability declares what that means for it in the project's
`migration_fleet` capability, `{"models": {"<model>": <fleet>}}`. The fleet is
release-evidence configuration, so it is its own document beside the
authoring declaration. There is one preflight and one release gate for every
project; the declaration is the only per-project part.

## Declaration

| `kind` | Databases rehearsed | Boot sequence | Other keys |
|---|---|---|---|
| `engine_tenants` | The engine's tenant databases on the environment's admin cluster, rostered with the reason each candidate is or is not a member | The engine's boot-time schema and history convergence | none |
| `named_databases` | `names`: databases on the environment's admin cluster | `converge_argv`, run from the project checkout with the copy's DSN bound to `runner.config.connection_env_var`; optional `verify_argv` runs the same way afterwards and must exit 0 | `schema_shape_sources`: checkout-relative files whose content is the schema the boot converges |
| `none` | Nothing | Nothing | `reason`: why this model has no live databases a release can rehearse |

```jsonc
// The engine's own model, under "models": {"primary": ...}.
{"kind": "engine_tenants"}

// A service converging its own registry database at boot.
{
  "kind": "named_databases",
  "names": ["service_registry"],
  "converge_argv": ["uv", "run", "--project", "services/svc", "python", "-m", "svc.schema", "init"],
  "verify_argv": ["uv", "run", "--project", "services/svc", "python", "-m", "svc.schema", "status"],
  "schema_shape_sources": ["services/svc/src/svc/schema.py"]
}

// One database on a host the admin cluster cannot copy.
{"kind": "none", "reason": "single SQLite database on the production host"}
```

A release gate refuses a model that declares no fleet, and a fleet for a model
the project's `migration_model` does not declare: an undeclared fleet and an
empty one are different facts. Create the document with
`yoke projects capability-settings set --project P --cap-type migration_fleet
--new --settings-json '{"models": {...}}'`; change one model with
`capability-settings merge --set models.<model>=<fleet JSON>`. Writing the
capability takes project-admin authority (`projects.capability_settings.set` /
`merge`), because a `named_databases` fleet names commands the release
machinery runs on an operator's machine. Those commands receive a minimal
environment — locale, home, temp, certificate paths, the project's `UV_*`
settings, the copy's DSN, and its restore point — never the operator's
credentials, and their failure output has the copy's DSN and password removed.

The admin cluster is the environment's `release.admin_connection` setting on
the project's own environment. A `named_databases` fleet runs from the
project's checkout registered on this machine (`yoke project register`), so
the declared commands find the code they converge with. A non-Python schema
source is digested byte for byte; a Python one by its syntax tree, so comments
and docstrings do not invalidate coverage.

## Preflight

```bash
yoke watch preflight -- --project P [--model M] [--checkout PATH] \
    <environment> [db ...] \
    --record-receipt --product-sha SHA --receipt-env <control-plane>
```

`--model` defaults to the capability's `default_model`. `--checkout` names the
checkout a `named_databases` fleet converges from (default: the project's
checkout registered on this machine). The live databases are
only read: each is dumped, restored into the local embedded cluster, converged,
verified, and dropped. A passing run with `--record-receipt` writes the
covered history entry names and the schema-shape digest onto that project
environment's own settings document under `release.fleet_rehearsal.<model>`,
on the prod release-gate control plane. Coverage is the union of passing runs
and never ages out; one environment's receipt never satisfies another, and one
model's never covers a sibling model that shares an entry name. A receipt
claims the whole declared fleet, so naming databases is a diagnostic run and
`--record-receipt` refuses it.

For a read-only census of the restored source, reuse that same copy path:

```text
yoke watch preflight -- --project P [--model M] <environment> [db ...] --instant-census-output DIR --copy-budget-gib N --minimum-free-gib N
```

This diagnostic mode does not apply history, converge schema or exercise
release-driver writes. It inspects a read-only copy transaction, retains
aggregate instant counts and archive/database sizes with phase timings before
cleanup, and cannot record a release receipt. Counts include blanks, missing
columns, unclassified candidate columns, invalid calendars and unknown offsets.
Separate format-shape counts identify qualified calendar text (including
PostgreSQL offset spellings), calendars without offsets, dates without times,
and other values. These shapes do not certify calendar validity or timezone
provenance; collection success does not authorize conversion. Original row bodies are not
logged. The explicit disk budget also counts concurrent filesystem consumption,
and the free-space floor remains required throughout each guarded transfer.
Put retained output on the copy filesystem. Inspect all refusals before retrying
or authoring a repair; this mode supplies no timezone or nullability decisions.

## Release gate

Before a deployment run dispatches a GitHub workflow for a project that
declares a `migration_model`, it reads every model's fleet. A `none` fleet is
skipped with its reason printed. An undeclared fleet refuses the dispatch with
the declaration recipe. Otherwise the gate reads the release commit's history
entries (from the model's `runner.config.modules_dir`) and schema-shape digest,
and when the target environment's receipts do not cover both it rehearses
exactly the release commit's code before dispatching: a `named_databases` fleet
converges from a disposable checkout of that commit, and an `engine_tenants`
fleet rehearses only after the dispatching engine's history bytes and schema
shape are proven identical to the commit's (otherwise it refuses and names the
release-driver recovery). It then re-reads coverage and refuses if the receipt
still falls short. The Yoke release workflow's pre-tag check,
`require_fleet_migration_preflight --project P <environment>`, reads the same
declarations and model-scoped receipts from a checkout of the release commit.

## Item rehearsal is a different receipt

`yoke migration rehearse PREFIX-N` proves the item's entry against the
validation surface and writes its receipt to `migration_audit` on the control
plane that holds the item, where the `implementing -> reviewing-implementation`
gate reads it. Fleet coverage is release evidence and lives on environment
settings. Neither substitutes for the other.
