# /yoke steer — worker lifecycle and frontier discipline

These rules bind `/yoke steer` launch behavior. They ship in this first
version: this file, the steering packet notes, and the launcher recipe
below. Do not defer them.

## 1. Encode dependency edges before frontier availability

Whoever files a batch of related items writes the `item_dependencies`
edges — or an explicit no-edges attestation — in the same action that
files them. Before launching a worker at a new item:

```text
yoke shepherd dependency-list PREFIX-N --json
```

Refuse to launch when a title-only related batch is already claimable
without edges or an attestation. A worker must never be sent at work the
frontier should not have offered.

## 2. Keep the frontier maxed out

Launch a worker promptly for every runnable unclaimed item in this
steering scope. Do not wait for the operator to pick. The backstop
(`steering.backstop.evaluate`) covers work that sat unpicked; prompt
staffing uses the launcher recipe below.

## 3. Launch CLI surfaces only

Steering-launched sessions use `claude-cli`, `codex-cli`, or
`cursor-cli`. Desktop surfaces only when the operator directs it or a
named exception scenario requires it.

```text
yoke session-control launch preview --project {_project} --surface cursor-cli --json
```

## 4. Launch item-bound, never via chaining `/yoke do`

The launch prompt names exactly one item, its routed skill entrypoint
(for example `/yoke dash PREFIX-N`), and a single-item mandate. Chained
sessions accumulate context rot; with steering active the steerer owns
selection, and chaining duplicates that selection.

## 5. Terminate the worker when the item is done

When a steering-scoped item reaches `done` and its closing report gives
the steerer everything needed:

```text
yoke sessions terminate {WORKER_SESSION_ID} --reason "PREFIX-N done"
```

Resolve `{WORKER_SESSION_ID}` from the launch that staffed the item
(`yoke session-control launch list --project {_project}` /
`yoke session-control launch get LAUNCH-ID`). No lingering. No re-tasking.

## 6. Every new item gets a fresh session

Never re-task an existing worker onto a different item. A new item is a
new `session_control.launch.create`.

## 7. Choose the model per item at launch

Default resolution: explicit `--model` on the launch > machine-config
`preferred_session_models` map > vendor default. Blank (or whitespace)
map values are unset and fall through to the vendor default. Override
per item when the work warrants — a heavier model for architecture,
migration, or high-risk items; a faster model for mechanical or
copy-level dashes. The override is the launch's explicit `--model`.
The resolved choice is recorded on the launch row.

```text
yoke session-control launch preview --project {_project} --surface {_surface} --list-models
```

## Launcher recipe

Preview, then create. The body is stdin. CLI surface only. One item.

```text
printf '%s' "$BODY" | yoke session-control launch create \
  --project {_project} \
  --surface cursor-cli \
  --stdin \
  --idempotency-key "steer:{_project}:{ITEM}" \
  --model {_model}
```

`$BODY` (replace PREFIX-N and skill). The steerer messages a worker with
`yoke say --item PREFIX-N --stdin`. The worker reports back with
`--session` only because the steerer is itemless (claim-less fallback).
Never expand a truncated session id by hand.

```text
/yoke dash PREFIX-N

Single-item mandate (steering): acquire the PREFIX-N work claim as your FIRST action, then execute only PREFIX-N to done. When it is done, message the orchestrator (printf %s "DONE PREFIX-N <one-line summary>" | yoke say --stdin --session {STEERER_SESSION_ID}) and END your session — do not pick up further work, do not chain into other items. If your claim is swept mid-work, reacquire and continue.
```

Route the skill entrypoint from the frontier step (`next_step` from
`yoke charge schedule`): `/yoke dash`, `/yoke blitz`, `/yoke refine`,
`/yoke shepherd`, `/yoke conduct`, `/yoke polish`, or `/yoke usher` —
never `/yoke do`.

The steering backstop composes the same single-item mandate for unpicked
work. Prefer `yoke steering backstop evaluate --project {_project}` for
work that sat; use this recipe for prompt staffing of newly runnable
unclaimed items. Both paths must stay item-bound and CLI-only.
