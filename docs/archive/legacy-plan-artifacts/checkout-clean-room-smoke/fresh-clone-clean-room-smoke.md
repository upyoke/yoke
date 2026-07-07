# G3.P1.I6 Fresh-Clone Clean-Room Smoke

This is the Phase 1 installability proof. It does not provision a database,
mint auth tokens, grant roles, or install a machine-wide CLI. It proves a fresh
checkout can install Yoke, write isolated `~/.yoke/config.json`, and use an
already-provisioned Postgres authority without legacy repo-local authority
files.

Run from a Yoke checkout:

```bash
python3 -m yoke_core.tools.checkout_clean_room_smoke \
  --dsn-file /path/to/authority.dsn \
  --json-output /tmp/yoke-i6-smoke.json
```

The tool creates a temp clone, temp `HOME`, temp `YOKE_MACHINE_HOME`, temp
venv, and temp config. It installs with `pip install -e .`, writes a config
from `yoke config example`, copies the DSN into the isolated machine home,
runs `yoke status --json`, emits one `CheckoutCleanRoomSmoke` event through
direct Python, reads an item with the in-checkout `yoke items get`, and reads
the emitted event back with `yoke events query`.

The proof fails if the clone contains repo-root `data/` or `projects/`, if the
runtime import comes from outside the clean clone, if `yoke` resolves outside
the clean venv, or if ambient DB env vars leak into the isolated command env.

## Verification Transcript

Run: June 8, 2026, from branch `codex/i6-cleanroom-smoke-20260608144843`.

Command:

```bash
python3 -m yoke_core.tools.checkout_clean_room_smoke \
  --source-root /Users/dev/yoke/.worktrees/i6-cleanroom-smoke-20260608144843 \
  --dsn-file /Users/dev/.yoke/secrets/yoke-cloud-prod.dsn \
  --keep-work-dir \
  --json-output /tmp/yoke-i6-clean-room-smoke-report.json
```

Result: pass.

- Clean clone: `/var/folders/.../yoke-i6-smoke-_eg6f9on/clone`
- Isolated machine config: `/var/folders/.../yoke-i6-smoke-_eg6f9on/home/.yoke/config.json`
- Isolated `yoke` executable: `/var/folders/.../yoke-i6-smoke-_eg6f9on/venv/bin/yoke`
- Runtime import origin: `/var/folders/.../yoke-i6-smoke-_eg6f9on/clone/runtime/__init__.py`
- DB status action: `probe_ok`
- Normal install proof: `pip install -e .` installed runtime dependencies including `psycopg` / `psycopg-binary`
- Direct Python write: event `69ebd625-6dde-4c82-9ffa-214cbf92369d`
- In-checkout CLI read: `yoke items get YOK-1 title --json`
- In-checkout CLI event readback: `yoke events query --event-name CheckoutCleanRoomSmoke --limit 1 --json`
- Ambient DB/project env leak check: `YOKE_PG_DSN`, `YOKE_PG_DSN_FILE`, `YOKE_PROJECT`, `YOKE_SCRATCH_ROOT`, and `YOKE_CONNECTED_ENV_DISABLE` all unset inside the smoke status report
