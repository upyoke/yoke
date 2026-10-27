# Execution levels

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Agents](index.md) > Execution levels
<!-- /yoke:breadcrumbs -->

Each execution level holds ordered model/minimum-effort rows.
Sessions take the highest matching threshold; manifests select catalog or native selectors.
Levels carry presentation and placement; workflow bindings select skills,
and steering or explicit operator staffing assigns work.

Execution levels are distinct from the claimed worktree lanes that isolate
code changes. See [worktree lanes and claims](rules/lanes-and-claims.md).

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
  With nothing stored, the universe reads the shipped scheme, so a newer
  Yoke release brings its new defaults as soon as the server runs it. A
  stored `universe_settings` row freezes that key at write time, so a later
  shipped default does not replace it; `yoke settings get levels --json` then reports
  `result.source: stored` with `result.shipped_defaults_differ` saying whether today's
  shipped defaults differ. `yoke settings unset levels` (org admin) deletes
  the stored levels so the universe follows shipped defaults again, and
  `set` with a document equal to the shipped defaults stores nothing.
  `cursor_quota_order` follows the same freeze rule; delete its row as
  described under the Cursor order below.

  ```text
  yoke settings get levels [--json]
  yoke settings get levels --json
  yoke settings set levels - < /tmp/levels.json
  yoke settings unset levels
  ```

  Save the edited `result.value` list in `/tmp/levels.json`.
  `universe.levels.set` replaces the whole definition and requires an org
  admin. It also refuses a threshold whose effort its
  model's published catalog values contradict (`level_min_effort_unpublished`). Model refresh proposes
  level changes with `yoke models level-proposal`; the operator approves
  before the proposed document is applied, with `yoke settings unset levels` when it equals the
  shipped defaults and `yoke settings set levels` otherwise. `yoke update --check` says whether
  the CLI or the server is behind the channel's latest release.
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

The item's work-claim holder or a live steering seat covering the item may
run the amendment, so steering can restaff an item a worker holds; any other
caller is refused with `claim_required`.
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
migration and retrying the amendment. The migration requires a live steering
seat covering the target project or document; workers cannot self-authorize it. `yoke workflows item-posture amend --help` carries the
recovery decision tree. Publishing a definition never blanket-repins items.

The override applies once to an automatic stage default: shift first, then
clamp to the named bounds and the project's level range. An exact
surface/model request bypasses the item default. A `--level` on an item-bound
create sets the override itself ([Launching by level](level-launches.md#launching-by-level)).
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
the exact successor `next_command`, and `read`, the path of this rule. A
merge close-out returns that same handoff and stops walking stages. Same level
and terminal targets return no handoff. This worker rule applies to every
harness and takes precedence over retaining a release-wait claim:

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

## Related

- [Launching and labeling execution levels](level-launches.md)
