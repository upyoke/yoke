# Key-value settings

`yoke settings list` shows each registered key's scope, value, source and meaning.
Use `--scope machine|project|org|universe` to narrow the list. Keys have unique
names across scopes; the key selects its authority. Project scope defaults to
the checkout; use `--project P` to select another project.

```text
yoke settings list --scope machine
yoke settings get max_active_worktrees
yoke settings set max_active_worktrees 12
yoke settings unset max_active_worktrees
yoke settings set levels - < /tmp/levels.json
```

Values use the declared type: strings are literal, integers and booleans use
JSON scalar syntax, and lists/objects use JSON. A value of `-` reads stdin.
Unknown keys name the closest match; invalid values name the type or range
and leave storage unchanged. Unset removes the override and follows defaults.
JSON reads carry the value in `result.value` (list rows in `result.settings`).

Machine settings stay in this computer's locked `settings` document. Project
writes require project admin; organization and universe writes require org
admin. `yoke machine access get|set` manages the registered machine's access
document. Structured capability documents, environment settings, surface policy,
execution instructions, UI preferences, connections and secrets retain their
own commands. Retention editing and project overrides of machine keys are
outside this catalog.
