# Execution levels

Each execution level holds ordered model/minimum-effort rows.
Sessions take the highest matching threshold; manifests select catalog or native selectors.
Levels carry presentation and placement; workflow bindings select skills,
and steering or explicit operator staffing assigns work.

Execution levels are distinct from the claimed worktree lanes that isolate
code changes. See [worktree lanes and claims](agent-rules/lanes-and-claims.md).

## The shipped scheme

Each level contains ordered base-model rows at their minimum effort:

| Level | Model | Minimum effort |
|---|---|---|
| INTERN 🐣 | claude-haiku-5-5, gpt-6-luna, claude-sonnet-5-5, gpt-5.6-terra, grok-4.7 | low |
| JUNIOR 🐥 | grok-4.7, gpt-5.6-terra, claude-sonnet-5-5 | high |
| | claude-opus-5-5, gpt-6.1-sol, claude-fable-5-1, gpt-6-astra | low |
| SENIOR 🦉 | claude-opus-5-5, gpt-6.1-sol, claude-fable-5-1, gpt-6-astra | medium |
| PRINCIPAL 🦅 | claude-fable-5-1, gpt-6-astra | xhigh |

## Document shape

Levels are a JSON list, lowest first. Names and glyphs follow their existing
contracts; each option is exactly a base model and minimum effort:

```json
[{"name":"SENIOR","glyph":"🦉","options":[
  {"model":"claude-opus-5-5","min_effort":"medium"},
  {"model":"gpt-6.1-sol","min_effort":"medium"}
]}]
```

There is no stored surface, context, speed or exhausted-pool fallback.
Within a model, thresholds must strictly increase with level; duplicate or
decreasing thresholds refuse `level_min_effort_order_invalid`. Base IDs carry
no native effort/speed suffix. Invalid rows name their field and correction.
`primary` is reserved and cannot name a level.

## Where levels live

- **Universe levels** — one definition per universe, in universe settings.
  With nothing stored, the universe reads the shipped scheme. A stored
  `universe_settings` row freezes that key at write time, so a later shipped
  default does not replace it. Delete the row with a reviewed
  `yoke operator data-repair` to follow shipped defaults again. Writing
  today's shipped document stores a new freeze. `levels` and
  `cursor_quota_order` follow this rule.

  ```text
  yoke universe levels get [--json]
  yoke universe levels get --json | <edit> | yoke universe levels set --stdin
  ```

  `universe.levels.set` replaces the whole definition and requires an org
  admin. It also refuses a threshold whose effort its
  model's published catalog values contradict (`level_min_effort_unpublished`). Model refresh proposes
  level changes with `yoke models level-proposal`; the operator approves
  before the proposed document is stored here.
- **Project override** — a project may carry its own levels in its
  `session-routing` capability, set only through the CLI. The document holds
  exactly one key, `levels`:

  ```text
  yoke projects capability-settings set --project NAME --cap-type session-routing \
    --settings-json '{"levels": [...]}' --new
  yoke projects capability-settings remove --project NAME --cap-type session-routing --base AS_READ_JSON
  ```

  Removing the capability returns the project to the universe levels.

Read what a project actually uses — the override when present, else the
universe levels — with `yoke projects level-summary get --project NAME`. The
result names its `source` (`project`, `universe`, or `default`).

## Launch capacity per level

`yoke universe level-capacity get [--json]` (`universe.level_capacity.get`)
reports each model row's native launch surfaces and current standing.
The harness manifest declares the selection source: Claude uses the active
researched catalog's Anthropic model ids and published efforts; Codex and
Cursor use native model listings per machine. Impossible provider pairs are
excluded before weighing. A native listing excludes models it does not offer.
An unknown listing requires `yoke relay probe-models --surface S`. An unsupported
listing names the missing adapter; ask the control-plane operator to provide it
or choose a surface with observed models. Neither invents availability.

Every candidate reads only the quota windows its model draws on. A readable
included zero blocks only when the surface's fresh paid extra-usage reading
says the provider will not bill past it: `disabled`, `cap_reached` or
`unavailable` (no funds). Extra usage that is `available`, `unsupported`,
`unknown` or `stale` (older than five minutes) leaves the launch to the
provider, whose own refusal stays authoritative; Yoke never enables spending,
raises a cap or buys credits. Missing or unreadable quota is unknown capacity.
Each relay reads extra usage with the same four-minute refresh as its windows:
Codex `credits` and `spendControlReached`, Claude `extra_usage`, and Cursor
`GetHardLimit` usage-based pricing (Cursor publishes no personal balance).
Pool output appends the shared phrase, for example `extra usage available
(balance 61,206.81 Codex credits)`. Each machine's
relay reads the manifest's quota source and reports named failures alongside
recovery guidance in the launch's pool output. Claude's 5-hour
window remains a separate cap beside its weekly limits. Cursor's two monthly
pools follow the order below. No level borrows another level's models.

Settings → Levels shows #, MODEL (ID and display name), MIN EFFORT and NOW,
plus Launchable on harness chips. The Cursor quota order appears below it as
two editable rows. Level configuration is edited through the registered CLI.

## Item level override

An item may override the level its workflow stage launches at. Level belongs
to the stage, independently of execution posture; the override is stored in
the `level` key of workflow posture and edited through its registered command:

```text
yoke workflows item-posture amend PREFIX-N --key level \
  --value '{"max": "SENIOR", "reason": "well-specified change"}' \
  --reason "steering staffing default"
yoke workflows item-posture amend PREFIX-N --key level --clear --reason R
```

The value is `{shift, min, max, reason}`: `shift` moves the level up
(positive) or down (negative) by that many levels, `min` and `max` name
levels the result is clamped to, and `reason` is required. At least one of
`shift`, `min`, or `max` is required; a non-integer or zero shift, an unknown
key, a name the project's levels do not include, or `min` above `max` refuses
by name. The steering report lists each override beside its level block.

Current published built-in definitions allow the key. Existing items keep
their immutable workflow pins when a new definition is deployed, so an old
pin may refuse the amendment, or a level-named launch's recording of it. Read
`yoke workflows item get PREFIX-N` for its actual allowlist. The control-plane
operator must select a compatible published version and preview `yoke
workflows item migrate PREFIX-N --version N --preview` before applying the
migration and retrying the amendment. This requires a live steering seat
covering the target project or document; workers cannot self-authorize it. `yoke workflows item-posture amend --help` carries the
recovery decision tree. Publishing a definition never blanket-repins items.

The override applies once to an automatic stage default: shift first, then
clamp to the named bounds and the project's level range. An exact
surface/model request bypasses the item default. A `--level` on an item-bound
create sets the override itself ([Launching by level](#launching-by-level)).
Changing an override never changes a running worker.

## Stage levels

Each workflow stage may declare `level`, naming an execution level. Every
non-terminal stage of the shipped workflows defaults to `SENIOR`; terminal
stages carry no level. New immutable versions carry these defaults; existing
item pins and historical definitions stay unchanged. The Workflows stage
strip shows the level glyph and name below the checks.

An item's effective level is its stage level plus the override's `shift`,
clamped to `min` and `max` and the project's lowest and highest available
levels. Item details shows a Level row after Status only when the effective
level differs from the current stage default. That row labels the stage value
Default and the effective item value Override, with the adjustment and reason.
A stored override resolving to the default shows no row. Missing or terminal
level data shows no row. Execution posture has no Level card on either the
item or Workflow page; workflow stage cards retain their level. Clearing the
override restores the stage default.

## Stage-level handoff

A lifecycle transition into a different effective level from the registered
worker returns `handoff` with `reason: level_change`, `stage_id`, `level`,
and the exact successor `next_command`. A merge close-out returns that same
handoff and stops walking stages. Same level and terminal targets return no
handoff. This worker rule applies to every harness and takes precedence over
retaining a release-wait claim:

1. Write a Progress Log checkpoint naming the live stage, committed and
   uncommitted lane work, and the next concrete step:
   `yoke items progress-log append PREFIX-N --headline "level-change handoff" --stdin`.
2. Release your claims with `yoke claims work release --all-mine --json`;
   read the receipt before continuing. Read `--help` for the release scope.
3. Run the returned `next_command` exactly. It launches this item's
   successor from the new stage's effective level. Read `launch create
   --help` for selectors and idempotency. Workers may launch their own
   successor after release; other workers and in-flight launches still block,
   and a worker still holding a claim refuses `item_has_live_worker`.
4. Verify the launch was accepted, then end the session. A refusal names its
   recovery: report it to steering and preserve the checkpoint; do not claim
   success or continue at the previous level. If the predecessor dies before
   launching, steering staffs the now-unclaimed item normally.

The successor reads the Progress Log and the preserved lane's status and log
before acting, then resumes from the checkpoint. The handoff is runtime
staffing, not an operator execution instruction or a workflow skill binding.

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
```

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
Capacity-stopped workers use [same-level recovery](session-capacity-recovery.md),
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
| Universe level glyph, `levels[N].glyph` | `universe.levels.set` | `yoke universe levels get --json`, correct the glyph, then `yoke universe levels set --stdin` |
| Project override level glyph, `levels[N].glyph` | `session-routing` capability settings | `yoke projects capability-settings set --project P --cap-type session-routing --settings-json '{"levels": [...]}' --base AS_READ_JSON` |
| Project emoji, `projects.emoji` (empty clears it) | `projects.create` / `projects.update` | `yoke projects update --slug S --name N --emoji <glyph>` |
| Workflow stage glyph, `stages[].glyph` | Workflow version publish | Publish an edited definition with `yoke workflows version publish WORKFLOW --definition-file F --expected-current-version N --reason TEXT` (`--keep-current` preserves the global default), then `yoke workflows item migrate ITEM --version V` |

`HC-stored-glyph-contract` FAILs on every stored value that breaks the
contract and prints its location with the correction command above.

## Session labeling and admission

A session takes the highest level containing its model where its effort meets
the minimum. Actual observed model/effort wins over launch stamps; requested
facts fill gaps. Native Cursor selectors supply embedded effort when needed.
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

Unknown models or unpublished effort (including Composer without published
efforts) establish no level. Item/epic-task claims and work launches refuse
`session_below_intern` with recovery when no level resolves. Steering without
item claims is exempt. Roster and identity reads show **no level**, never
`primary`. Registration and observed-model updates refresh stored labels.

## Cursor quota order

`universe.cursor_quota_order.get` and `.set` read or replace the universe-wide
order of exactly two Cursor monthly pools. It is not per machine:

```text
yoke universe cursor-quota-order get --json
yoke universe cursor-quota-order set --pool 'Cursor Models' --pool 'Other Models'
```

Repeat `--pool` exactly twice; reverse them to prefer Other Models. Invalid,
duplicate or missing scopes refuse `cursor_quota_order_invalid`. The order
affects consumption preference, never execution-level membership. An absent
row uses the shipped order (Cursor Models, then Other Models). A stored row
freezes that order; delete it with a reviewed `yoke operator data-repair`
to follow the shipped order again.

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
