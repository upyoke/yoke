# Machine config — env-keyed connections inside one file

Decision date: 2026-06-10 (G3.P3.I0A writer-UX slice). Status: decided.

## The contradiction this resolves

GEN-3-PLAN §2.P says "there is still no separate env registry in v0,"
while the same plan promises UX that requires per-env connection
details to exist somewhere:

- bare `yoke env use stage` as "the normal operator convenience"
  after Phase 3 packaging (§1.6.6/§2.P);
- per-command `--env stage` / `YOKE_ENV=stage` *routing* (§2.Q) — not
  merely an assertion against the configured env.

The I4C-era singleton `connection` object could not satisfy either:
switching envs meant hand-rewriting transport/api_url/credential
together, and `selected_env` hard-errored on any `--env` that differed
from the configured one.

## Decision

`~/.yoke/config.json` carries an env-keyed **`connections`** map plus
an **`active_env`** default pointer. "No separate env registry" is read
as: no second file, no DB-side env catalog, no per-project env binding —
the one machine config file is the whole registry.

```jsonc
{
  "schema_version": 1,
  "active_env": "prod",
  "connections": {
    "prod":  {"transport": "local-postgres", "credential_source": {...}, "postgres": {...}},
    "stage": {"transport": "https", "api_url": "https://app.stage.upyoke.com/api/orgs/yoke-stage",
               "credential_source": {"kind": "token_file", "path": "~/.yoke/secrets/stage.token"}}
  }
}
```

- Env precedence is unchanged (`--env` > `YOKE_ENV` > `active_env`),
  but a non-default env now **routes** to its configured connection for
  that invocation instead of erroring. An env with no entry fails
  loudly naming the configured labels.
- `contract.active_connection` returns the selected entry with the
  resolved label injected as `env`, so downstream readers
  (`yoke_transport`, `yoke_connected_env`, status) kept their
  reader shape across the cutover.
- The singleton `connection` object is deleted, not aliased — readers,
  validation codes (`connection_required`, `env_required`,
  `env_mismatch`), fixtures, and the canonical example all moved in the
  same slice (founder cutover; no transitional readers).

## Env-scoped project mappings

`projects` is a **flat list** of `{checkout, project_id, env, board?}`
entries. Because project ids are numbered **per universe** (each
connection env's `projects` table starts at 1), a bare `project_id`
alone is ambiguous — the same integer names different projects under
different envs. Each entry therefore carries an explicit `env`, and a
checkout that lives in several universes appears **once per env** — the
rows are identical apart from `env` (and any per-env id):

```jsonc
"projects": [
  {"checkout": "/Users/example/yoke", "project_id": 1, "env": "prod",  "board": {...}},
  {"checkout": "/Users/example/yoke", "project_id": 1, "env": "stage", "board": {...}}
]
```

- **Why a list, not a checkout-keyed object.** A checkout genuinely maps
  to a different project id in each universe it deploys to, and a JSON
  object cannot repeat the checkout key. The flat list holds one row per
  `(checkout, env)` — simple rows, duplication across envs is expected
  and fine.
- **Resolution is env-aware.** `project_entry_for_checkout(payload,
  repo_root, env=...)` returns the row whose `checkout` matches AND whose
  `env` matches the resolved connection env (`--env` > `YOKE_ENV` >
  `active_env`), flattened to `{project_id, env?, board?}`. A checkout
  with no row for the requested env does **not** resolve — the lookup
  falls through rather than returning a wrong-universe project. Readers
  (`project_id`, `installed_project_ids`, `configured_projects`) inherit
  this scoping.
- **Registration is a per-`(checkout, env)` upsert.** `upsert_project_entry`
  replaces the row for the same checkout AND env, leaving that checkout's
  rows for other envs intact. No cross-checkout deduplication is
  performed — the rows are independent.
- **Validation requires `env`.** Each entry must carry a non-empty `env`
  that names a configured connection (`project_env_required` warns when
  missing, `project_env_unknown` errors when unconfigured).
  `schema_version` stays `1`: reads stay permissive so a not-yet-stamped
  legacy config keeps resolving (an untagged row matches only the
  `active_env`), and an explicit repair — not a silent load-time upgrade —
  stamps the file.
- **Legacy shape still read.** The previous checkout-keyed object
  (`{checkout: {project_id, env?}}`) is normalized to the list form on
  read, so an unstamped machine keeps working until the repair runs.
- **Repair.** `yoke [--env ENV] config stamp-project-env` normalizes the
  container to a list and stamps every untagged row with the chosen env
  (default: the current `active_env`; the creating env cannot be recovered
  from an untagged row), logs each stamp, and leaves already-tagged rows
  untouched. `yoke project register` upserts a `(checkout, env)` row from
  the connection env the registration runs under.

## Writer UX (machine-local only; never project repos, never the DB)

- `yoke connection set ENV --transport T [--api-url URL]
  [CREDENTIAL | --token-file P | --token-stdin | --dsn DSN | --dsn-file P
  | --dsn-stdin]` — create/update one entry; creating requires
  `--transport`; a positional credential is stored as a DSN for
  `local-postgres` envs and as a token otherwise; the first configured
  env becomes `active_env` (a fresh config with a dangling default would
  fail validation).
- `yoke env use ENV` — flip `active_env` to an already-configured env.
- `yoke auth set ENV [CREDENTIAL | --token-file P | --token-stdin |
  --dsn DSN | --dsn-file P | --dsn-stdin]` — set/rotate the credential;
  positional credentials use the env transport to choose token vs DSN.
  Secret values are stored under `~/.yoke/secrets/<env>.<suffix>`
  (0600) and only the file reference lands in config. Raw secret values
  never land in the config or in command output.
- `yoke project register REPO_ROOT --project-id N [...]` — upsert a
  `{checkout, project_id, env}` row; `env` is the connection env the
  registration runs under (`--env` > `YOKE_ENV` > `active_env`). Register
  the same checkout under another env to add its row for that universe.
- `yoke [--env ENV] config stamp-project-env` — normalize the `projects`
  container to a list and stamp `env` onto every untagged legacy row
  (default env: `active_env`).

Every writer validates the FULL resulting payload against the contract
before writing and refuses (naming the contract issue codes) rather
than landing an invalid file; writes are atomic (`.tmp` + rename, 0600).
The env argument is positional because the CLI's global `--env` flag is
extracted before adapters parse.

`yoke self update` stays the documented pipx equivalent
(`pipx upgrade yoke-cli`) per the packaging decision record.
