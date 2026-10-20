# Launching and labeling execution levels

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Agents](index.md) > Level launches
<!-- /yoke:breadcrumbs -->

Use execution levels to place launched sessions, interpret their labels and converge stored routing settings.

## Launching by level

A create with no selector uses the item's live effective stage level, and
Yoke chooses the option and machine; it records nothing. An explicit `--level`
on an item-bound create also records that level as the item's override for
every stage, `{"min": L, "max": L, "reason": R}`, in the launch's own
transaction and with the launching seat's own authority (no claim is acquired
or released). The worker is therefore not handed off at its first stage edge.
`--level-reason R` states why (default `launch-time level`); the result's
`item_level` (`level`, `reason`, `changed`, `previous`) echoes it, and a launch
that fails records nothing. A pin that does not allow `level` refuses
`item_level_not_recordable`; an item-bound create against a server that predates
the recording prints `item_level_unrecorded`. A preview, an itemless create,
and an exact surface place one launch only. A missing stage level without an
explicit selector refuses as `stage_level_missing`, naming `--level` or the
steering-seat workflow migration
preview/apply prerequisite for an existing old pin. Select a compatible
published version; new versions never move existing pins automatically.
`HC-workflow-stage-level-pins` fails naming every non-terminal item pinned to a
version with a level-less stage, with its exact
`yoke workflows item migrate PREFIX-N --version N --preview` recipe:

```text
yoke session-control launch preview --project P --level SENIOR [--machine M] --json
yoke session-control launch create --project P --item PREFIX-N --idempotency-key K
yoke session-control launch list --project P --item PREFIX-N   # launches that staffed the item
```

An item-bound launch names its session `PREFIX-N: title`; the list's ITEM
column and `--item` filter read that prefix.

Placement expands each model row through its manifest's selection source at its minimum
effort. Machine access, lane capacity and quota rules remain authoritative.
Empty/blocked candidates are skipped. Among available Cursor candidates,
the earlier monthly pool is preferred before headroom; other vendors have
no pool order. Headroom is per worker: a pool's headroom divided by the live
workers and unregistered launches on the same machine whose model that pool
covers, plus the new launch. The spread rule prefers an option whose binding
pool has no worker and more than 100% headroom, followed by per-worker
headroom and configuration position. Level launches place one at a time, so
each launch in a burst counts the earlier ones.
Unknown quota, and unknown or stale extra usage, never mean exhaustion.

When no native selection can launch, `level_no_capacity` names each refusal
and its recovery. Unknown levels refuse `level_unknown`. The retired JUNIOR
exhausted-to-Cursor-Opus fallback no longer exists: Cursor Opus medium resolves
as SENIOR, and cannot be inserted into JUNIOR as an exhaustion escape.
Capacity-stopped workers use [same-level recovery](capacity-recovery.md),
excluding the refused model.

The launch result, `launch preview`, and `launch get` name the level, the
chosen option, every pool each option read, and why the winner won
(`level_placement`). Options name their machine by its registered name, as
the steering report does; `Selected machine` keeps the id `--machine`
takes. Each pool shows quota left, headroom, the live workers drawing on it
(`workers`) with the per-worker split (`share_percent`), and its reset in
UTC; an option's `headroom_percent` is its binding pool's split. The
stored launch keeps the level as its ask, and `launch retry` places the
level again. `--machine` narrows placement to one machine.

An explicit `--surface` (with `--model`, `--reasoning-effort`,
`--context-window` as needed) still launches exactly as asked and is
recorded as `selection: override`. A level and explicit knobs are exclusive
(`level_selection_conflict`). `level` is a new argument of the launch
functions: an HTTPS server older than its serving floor rejects it, and the
CLI refuses as `function_argument_version_skew`, naming the floor and the
explicit form that server still accepts. The CLI marks a selector-free create
with `use_stage_level: true`, an argument with its own serving floor, so an
older server names the unavailable stage default and the explicit selector
recovery rather than silently launching another level.

## Glyph contract

`yoke_contracts.glyph_contract` requires one `Emoji_Presentation=Yes` code point
(category `So`, East Asian Width `W`), without variation selectors, modifiers,
ZWJ, flags, keycaps or combining marks. Writers refuse unsafe glyphs by name,
quoting the code point and offering safe examples such as 🐎 or 🚀:

| Stored glyph | Writer | Correction command |
|---|---|---|
| Universe level glyph, `levels[N].glyph` | `universe.levels.set` | `yoke settings get levels --json`, correct the glyph, then `yoke settings set levels -` |
| Project override level glyph, `levels[N].glyph` | `session-routing` capability settings | `yoke projects capability-settings set --project P --cap-type session-routing --settings-json '{"levels": [...]}' --base AS_READ_JSON` |
| Project emoji, `projects.emoji` (empty clears it) | `projects.create` / `projects.update` | `yoke projects update --slug S --name N --emoji <glyph>` |
| Workflow stage glyph, `stages[].glyph` | Workflow version publish | Publish an edited definition with `yoke workflows version publish WORKFLOW --definition-file F --expected-current-version N --reason TEXT` (`--keep-current` preserves the global default), then `yoke workflows item migrate ITEM --version V` |

`HC-stored-glyph-contract` FAILs on every stored value that breaks the
contract and prints its location with the correction command above.

## Session labeling and admission

A session takes the highest level containing its model where its effort meets
the minimum. Actual observed model/effort wins over launch stamps; requested
facts fill gaps. Observed effort comes only from the harness artifact for the
latest turn; Codex rereads its rollout on every hook, so a mid-session change
lands. Configuration files and catalog defaults never supply it. A turn whose
artifact names no effort records `not_reported`: the session takes the lowest
level and shows `session_effort_not_reported` (effort not reported by the
harness) until the harness reports an effort. Native Cursor selectors supply embedded effort when needed.
Speed selectors such as `-fast` are stripped and ignored. Effort order is
none < minimal < low < medium < high < xhigh (extra-high) < max < ultra.
No model ranking table participates.

A known older model with a catalog `replacement_model_id` and no explicit
entry drops exactly one class at the same effort, regardless of version age:
Claude Haiku < Sonnet < Opus < Fable; OpenAI Luna < Terra < Sol < Astra.
The current lower-class model supplies its thresholds. Older bottom-class
Haiku/Luna and single-class Grok refuse. Opus 4.8 medium resolves as current
Sonnet medium and INTERN. Grok 4.7 high-fast resolves as JUNIOR; Cursor Opus
5.5 medium resolves as SENIOR.

Unknown models, unreported effort or unpublished effort (including Composer without published
efforts) establish no level. Item/epic-task claims and work launches refuse
`session_below_intern` with recovery when no level resolves. Steering without
item claims is exempt, and so is `yoke items cancel`: cancelling is an
administrative close, not work. Roster, identity, board and steering reads show
**no level** with its reason, never `primary`: `session_model_unknown`
(model not in the catalog), `session_effort_unreported` (no effort
reported for the session), `session_effort_unpublished` (effort not
published for its model), `session_model_unreported`,
`session_older_model_bottom_class`, `session_demotion_target_unavailable` or
`session_below_minimum_effort`. Session list rows carry the code as
`level_reason`. Registration and observed-model updates refresh stored labels.

## Cursor quota order

`universe.cursor_quota_order.get` and `.set` read or replace the universe-wide
order of exactly two Cursor monthly pools. It is not per machine:

```text
yoke settings get cursor_quota_order --json
yoke settings set cursor_quota_order '["Cursor Models", "Other Models"]'
```

Pass a JSON array containing both pool names once each; reverse them to prefer Other Models. Invalid,
duplicate or missing scopes refuse `cursor_quota_order_invalid`. The order
affects consumption preference, never execution-level membership. An absent
row uses the shipped order (Cursor Models, then Other Models). A stored row
freezes that order; `yoke settings unset cursor_quota_order` (org admin)
restores the shipped order.

## Stored settings convergence

Serving-build boot converges retired surface-selector rows into model/minimum-effort
rows and initializes the two Cursor pools, with a serving floor preventing old
readers. Operator-approved replacement content is set after landing and candidate
serving through the registered writer.

Levels replaced three older `session-routing` keys — declared level
metadata, selector rules, and harness defaults. Boot removes them from every
stored project document through the ordered migration history and deletes a
document left without levels, so every project reads the universe levels
unless it holds a real override. A write that still uses a retired key is
refused as `level_routing_keys_retired` with the override recipe above.

Retired machine launch-default keys keep loading; `yoke status` names them as
`machine_config_key_retired`, and the next config write removes them.

## Related

- [Execution levels](levels.md)
