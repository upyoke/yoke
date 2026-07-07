# Yoke operations CLI — machine packaging + transport-branch shape

Decision date: 2026-06-10 (G3.P3.I0A). Status: decided.

## Packaging: the Python wheel, installed machine-scoped via pipx

The machine-scoped `yoke` CLI is the existing Python wheel
(`pyproject.toml` `[project.scripts]` console-script `yoke`), installed
outside any checkout with pipx:

```
pipx install yoke-cli --pip-args="--no-index --find-links /path/to/yoke-wheelhouse"
pipx upgrade yoke-cli --pip-args="--no-index --find-links /path/to/yoke-wheelhouse"
```

Rationale against the alternatives the plan named (GEN-3-PLAN §2.Q):

- **Python wheel / pipx (chosen).** Zero second implementation: the
  in-checkout entrypoint, flag adapters, typed envelopes, and machine
  config resolver ship as-is. pipx gives an isolated venv + a stable
  `yoke` on PATH at machine scope, and `pipx upgrade` is the
  self-update story. `psycopg[binary]` is already a core dependency, so
  the same install can run local-postgres transport for self-hosters.
- **Homebrew formula (deferred, compatible).** Worth adding when
  distribution beyond the operator's machines matters; a formula wraps
  the same wheel, so nothing here forecloses it.
- **Single-file static binary (rejected).** Would re-implement envelope
  authoring in a second language — explicitly banned by §2.Q's no-second
  -registry/no-second-envelope rule.
- **PyInstaller frozen Python (rejected).** Buys "no Python required" at
  the cost of a large artifact and a second build pipeline; the operator
  population in Gen 3 (founder + self-hosters cloning a Python repo)
  already has Python.

## Transport branch: configured transport, not import availability

The plan's early sketch keyed the HTTPS relay on "`runtime.api.*` is not
importable." Implementation reality supersedes it: the wheel always
carries `runtime.*`, so import availability cannot distinguish a
checkout from a machine install. The branch condition is the machine
config's **active connection transport** (`~/.yoke/config.json`,
env-keyed `connections` map per
`docs/archive/decisions/machine-config-env-connections.md`):

- `transport: "local-postgres"` on the selected env — in-process
  dispatch against the selected Postgres authority
  (dev/admin/self-host mode);
- `transport: "https"` on the selected env —
  `yoke_cli.transport.https` POSTs the identical
  `FunctionCallRequest` envelope to `{api_url}/v1/functions/call` with
  the machine credential as `Authorization: Bearer`, and parses the
  typed `FunctionCallResponse` back. The routing chokepoint is
  `call_dispatcher` in `service_client_structured_api_adapter`, so every
  `yoke <subcommand>` adapter inherits the relay with no per-adapter
  work.

The machine credential for https is `credential_source.kind:
"token_file"` — a permission-locked file holding the actor token minted
by `runtime.api.domain.api_tokens_cli`. The cloud boundary overwrites
the envelope actor from the verified token, so locally-resolved session
identity is advisory context, never authority. A half-configured https
connection (missing api_url, missing/unreadable token) fails loudly with
the repair surface named (`yoke status` / `yoke config example`);
it never falls back to local authority.

The env-keyed `connections` map and
the `yoke env use` / `yoke connection set` / `yoke auth set` /
`yoke project register` writer UX landed in the next G3.P3.I0A slice
(`docs/archive/decisions/machine-config-env-connections.md`).
