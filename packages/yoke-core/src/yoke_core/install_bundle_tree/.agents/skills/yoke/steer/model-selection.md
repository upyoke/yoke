# /yoke steer — choosing a level for a launch

Every `session_control.launch.create` names a **level**, and Yoke chooses the
option and the machine. This file is how the steering seat decides which
level to name. It applies to **new launches only** — a running session keeps
the selection it started with, and changing a worker's level means launching
a replacement, never editing a live one.

## Choose the level for the current leg

Judge the work remaining at the item's live stage, not just its title or the
level that started it.

| The current leg is | Level |
|---|---|
| Definition (idea, refine, shepherd), implementation, pre-merge review/polish — the default | `SENIOR` |
| Well-specified mechanical edits, documentation, routine cleanup | `JUNIOR` |
| Trivial, fully specified changes | `INTERN` |
| Genuinely very complex debugging or architectural decisions | `PRINCIPAL` |

When the remaining work becomes mechanical, downshift the next leg to a lower
level with the restaff recipe below rather than waiting for a new item. These
are staffing judgments, not static per-skill routing.

The levels a project reads, and each level's options, are data:

```text
yoke projects level-summary get --project {_project}
yoke universe levels get
```

Never restate those options here; the next level edit would leave this file
teaching a selection the universe no longer has.

## How a level launch is placed

```text
yoke session-control launch preview --project {_project} --level SENIOR --json
```

That launches nothing. It weighs every option of the level on every machine
you may use, against only the quota pools that option's model draws on, keeps
a worker on every idle surface above 100% headroom, and otherwise picks the
most headroom. The receipt names the level, the chosen option, every pool
each option read, and why the winner won (`level_placement`). The rules and
their edge cases live in
[launching by level](../../../../.yoke/docs/reference/session-level-routing.md#launching-by-level).

A Cursor option draws on **Cursor Models**; its fallback (Opus, on **Other
Models**) is placed only where the Cursor Models pool reads zero. Plenty of
Other Models quota, an unreadable meter, or low headroom are not exhaustion
and never move a launch onto the fallback.

When no option of the level has capacity, the launch refuses as
`level_no_capacity`, naming each option and the pool that blocked it. Yoke
never borrows another level's options. Decide: relaunch at a different
`--level` if the work allows it, wait for the named reset, or raise the wall
with the operator. Never pick a different level silently to get a worker
started.

## Explicit selections are operator overrides

When the operator asks for an exact model ("Opus 5.5 medium"), launch exactly
that with `--surface` and the knobs instead of `--level`; the launch is
recorded as `selection: override`. A level and explicit knobs are exclusive
(`level_selection_conflict`).

Each harness publishes its own accepted efforts and context windows, and a
name one surface accepts another refuses. Read them before naming one:

```text
yoke session-control launch create --project {_project} --surface {_surface} --list-models
```

That prints the efforts and context windows the CLI accepts for the surface
and this machine's observed native models. The manifest
`session_control.launch_model_selection` at
`runtime/harness/<harness-dir>/manifest.json` is the fact it reads.

Effort levels come from what the specific **model** publishes, which can be
narrower than what the surface accepts; asking for a level a model never
offered is a launch the vendor rejects.

For Cursor, use the exact selector from that machine's native listing and
omit a separate effort when the selector already names it. A matching
separate effort is accepted once; a conflicting effort is refused. Omit
`--context-window` unless the exact variant's native description names that
window. If availability is unknown, refresh it with
`yoke relay probe-models --surface cursor-cli` on the target machine, then
preview again.

## Adopting a new model

Availability is observed natively, so a new model appears the moment the
surface publishes it; missing research never gates a launch. A new model
reaches a level only when the operator approves a change to the levels:
`yoke models level-proposal` proposes it, and `yoke universe levels set`
stores the approved document. `/yoke models` reviews the researched catalog
(`yoke models get`, or one model with `yoke models lookup <model-id>`); the
catalog holds facts about models and never moves a level option by itself.

## Retry once, then restaff the same item

A local implementation or verification failure gets one retry from the same
worker: diagnose the named failure, correct it, and rerun the failed check.
A second failure, or a spec/design misunderstanding on the first attempt,
gets a fresh session one level up, seeded from the Progress Log. Do not spend
another retry on a misunderstanding or treat a parked delivery/landing wait
as a failure.

Use rule 9 in [`worker-lifecycle.md`](worker-lifecycle.md): read or request the
checkpoint, terminate the predecessor, verify its claim is released, preview
and launch the successor on the same item at its current stage, then confirm
registration and claim ownership. The checkpoint names the live stage,
committed and uncommitted work, the failure evidence or misunderstanding, and
the next concrete step. The successor reads it and the preserved lane before
acting; it continues the item rather than repeating completed legs.

If the worker is already at the highest level, or the next level has no
capacity, report that ceiling and the failure evidence to the operator for a
decision; do not promote silently. Use the same handoff when downshifting the
next mechanical leg.

A native resume retains that session's attested selection: Claude restores
it, and Codex and Cursor re-send it. To change the level for the item,
restaff it: launch a successor at the new level through rule 9; do not edit
the running session's model.
