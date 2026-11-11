# Fleet Preflight Box Identity

A box that runs fleet preflight beside a database fleet (an environment's
`release.preflight_executor`) reads that environment's release settings and,
after the whole fleet passes, records its receipt on the control plane. It
calls as its own machine account, never with a person's token.

## Shape

| Fact | Value |
|---|---|
| Actor | `kind=system`, one `system_component` per box |
| Grant | project role `preflight_executor` on each project whose fleet the box rehearses |
| Permissions | `items.read` and `release.fleet_rehearsal.record`, nothing else |
| Custody | `~/.yoke/secrets/platform-<env>-box-preflight-control-plane-token`, mode `0600` |

`release.fleet_rehearsal.record` authorizes `projects.environment_settings.merge`
only when every assigned path lies under `release.fleet_rehearsal.`. A merge
that names any other path, including the bare `release.fleet_rehearsal`
container, needs `project.admin` and is refused as `permission_denied`.
Owners and admins keep receipt writes through their wildcards. The role is
machine-only: no person grant or invite offers it.

What the box calls, end to end, and why the role covers it:

| Call | Needs |
|---|---|
| `projects.environment_settings.get` (`release.preflight_executor`, `release.admin_connection`, receipt-plane probe) | `items.read` |
| `projects.capability_settings.get` (`migration_model`, `migration_fleet`) | `items.read` |
| `projects.get` (a `named_databases` fleet without `--checkout`) | the project grant |
| `projects.environment_settings.merge` of `release.fleet_rehearsal.<model>.*` | `release.fleet_rehearsal.record` |

`yoke connection set --token-stdin` and installing or updating the engine call
no control-plane function. Relay retry telemetry (`events.emit`) needs
`events.write`, which the role does not carry; that record is refused and
quarantined, and the preflight is unaffected.

## Which projects

A receipt is stored on the rehearsed project's own environment: Yoke's engine
tenant fleet under project `yoke`, Platform's registry fleet under project
`platform`. Grant the role on every project whose fleet the box rehearses; a
Platform environment box rehearses both, so it names both.

## Recipe

Every real record lives on the production control plane, so each box's account
is created there, with admin database authority, one command per box. The raw
token goes straight to the custody file and is never printed:

```bash
mkdir -p -m 700 ~/.yoke/secrets
YOKE_ENV=prod-db-admin python3 -m yoke_core.domain.api_tokens_cli \
  bootstrap-project-service \
  --system-component platform-<env>-box-preflight \
  --project yoke --project platform \
  --role preflight_executor \
  --name platform-<env>-box-preflight \
  --raw-token-file ~/.yoke/secrets/platform-<env>-box-preflight-control-plane-token
```

Use `stage` or `prod` for `<env>`, the box's environment. The command prints
only the token and actor ids. Place the file on the box with Platform's
`place_box_secrets.py`; the box connects with `yoke connection set
--token-stdin` reading that file.

The actor and grants converge idempotently, and every run mints another active
token. Rotation reruns the same command with the same projects (a different
project list is a different scope and is refused), installs and verifies the new
file, then revokes the old token with the same entrypoint:
`revoke --token-id <id>`.
