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
    "stage": {"transport": "https", "api_url": "https://api.stage.upyoke.com",
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
- `yoke project register REPO_ROOT --project-id N [...]` — checkout →
  integer project id mapping.

Every writer validates the FULL resulting payload against the contract
before writing and refuses (naming the contract issue codes) rather
than landing an invalid file; writes are atomic (`.tmp` + rename, 0600).
The env argument is positional because the CLI's global `--env` flag is
extracted before adapters parse.

`yoke self update` stays the documented pipx equivalent
(`pipx upgrade yoke-cli`) per the packaging decision record.
