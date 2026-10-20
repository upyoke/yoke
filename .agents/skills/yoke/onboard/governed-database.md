# Onboard Step 5: Governed Database

Row: `migration-model-setup`. History, connection variable and ledger are
project facts, never Yoke defaults.

- Declare now: `sqlite_file` or `postgres`, shaped per
  [migration-model.md](../../../../.yoke/docs/databases/migration-model.md);
  set the `migration_model` capability and read it back.
- Attach later: write nothing; `deferred` names missing coordinates.
- None: `not-needed`; item DB claims stay `none`.

Onboard never applies or rehearses migrations.
