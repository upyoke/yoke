# Execution levels

An execution level is a named, ordered capability band. Each level holds an
ordered list of **options**, and each option is one exact launchable
selection. The same options label sessions: a session is stamped with the
level whose option matches its harness, model, and effort. Levels carry
identity, presentation, and launch selections; workflow bindings select stage
skills, and steering or explicit operator staffing assigns work.

Execution levels are distinct from the claimed worktree lanes that isolate
code changes. See [worktree lanes and claims](agent-rules/lanes-and-claims.md).

## The shipped scheme

Every universe reads this scheme until an operator stores its own, lowest
level first:

| Level | Surface | Model or selector | Effort | Context |
|---|---|---|---|---|
| INTERN 🐣 | claude-cli | `claude-haiku-4-5` | max | default |
| | codex-cli | `gpt-6-luna` | max | default |
| JUNIOR 🐥 | cursor-cli | `grok-4.7-high`; when its pool is exhausted, `claude-opus-5-5-medium` | high / medium | default |
| | codex-cli | `gpt-5.6-terra` | xhigh | default |
| | claude-cli | `claude-sonnet-5-5` | xhigh | 1,000,000 |
| SENIOR 🦉 | claude-cli | `claude-opus-5-5` | medium | 1,000,000 |
| | codex-cli | `gpt-6.1-sol` | medium | default |
| PRINCIPAL 🦅 | claude-cli | `claude-fable-5-1` | xhigh | 1,000,000 |
| | codex-cli | `gpt-6-astra` | xhigh | default |

## Document shape

Levels are a JSON list, lowest first:

```json
[
  {
    "name": "SENIOR",
    "glyph": "🦉",
    "options": [
      {"surface": "claude-cli", "model": "claude-opus-5-5",
       "reasoning_effort": "medium", "context_window_tokens": 1000000},
      {"surface": "codex-cli", "model": "gpt-6.1-sol",
       "reasoning_effort": "medium", "context_window_tokens": null}
    ]
  }
]
```

- `name` is uppercase letters, digits, and underscores, unique, and never the
  reserved unresolved name `primary`.
- `glyph` satisfies the [glyph contract](#glyph-contract).
- An option names a launch `surface` (`claude-cli`, `codex-cli`,
  `cursor-cli`), one exact `model` or native selector (no wildcard), the
  `reasoning_effort`, and `context_window_tokens` (`null` for the model's
  default window). Effort and context are validated against what that
  surface's CLI accepts — claude-cli takes `low`, `medium`, `high`, `xhigh`,
  `max` and a 1,000,000-token window; a Cursor selector that encodes an effort
  must name the same effort.
- A Cursor option may carry a `fallback` on the same surface, used only when
  the option's own pool is exhausted.
- One surface, model, and effort belongs to at most one level.

A refusal names its code (for example `claude_reasoning_effort_unsupported`,
`level_option_model_not_launchable`, `level_glyph_unsafe`) and the document
path to correct.

## Where levels live

- **Universe levels** — one definition per universe, in universe settings.
  With nothing stored, the universe reads the shipped scheme.

  ```text
  yoke universe levels get [--json]
  yoke universe levels get --json | <edit> | yoke universe levels set --stdin
  ```

  `universe.levels.set` replaces the whole definition and requires an org
  admin. It also refuses an option whose effort or context window its
  model's published catalog values contradict
  (`level_option_reasoning_effort_unpublished`,
  `level_option_context_window_tokens_unpublished`). Model refresh proposes
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

Read what each universe level can launch right now with
`yoke universe level-capacity get [--json]` (`universe.level_capacity.get`).
For every option it names the quota pools that option's model draws on
(Claude rolling 5h, weekly all-models and weekly model-specific; Cursor Models
or Cursor Other Models; Codex weekly), each pool's quota left and headroom,
and the option's standing:

- **Can launch** — every readable pool it draws on has quota left on a usable
  machine. A Cursor option whose own pool is exhausted launches its fallback,
  shown as `via` the fallback model.
- **Blocked** — a pool it draws on reads 0% left, or no usable machine offers
  its surface. Each blocker is named. An unreadable or unpublished meter never
  blocks; it leaves the headroom unknown.

A level with no launchable option has **no capacity**. Usable machines, meters
and live workers are the union across the universe's live projects.

Per level and per live project it names where your next launch at that level
goes and why (`next_launches`). The read does not predict placement: it runs
the same preview `launch preview --level` runs, as you, in that project — the
placement described under [Launching by level](#launching-by-level) — so its
answer is the answer a launch would get. A preview that would refuse (no
option with capacity, the level not defined by the project's override, or you
not an operator there) is listed with its code and reason. The read also lists
every project and what its override, if any, changes.

A steering seat reads the same standing from its own fleet report: the
**levels** block dry-runs a launch at every level the project reads, under the
seat's own launch authorization, and names each option's machine, pools
(left, headroom, reset), blocker, and where the next launch goes and why,
beside the fleet-wide live workers per launch surface
([steering fleet report](db-reference/steering-fleet-report.md)).

The dashboard's **Settings → Levels** page, directly under Universe, shows
this read: levels, options, capacity, each project's next launch per level,
and project overrides with the override command. It is view only; edit levels
with the commands above.

## Item level override

An item may carry its own override of the level its stage launches at, as the
`level` key of its workflow posture:

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
pin may refuse the amendment. Read `yoke workflows item get PREFIX-N` for
its actual allowlist. The control-plane operator must select a compatible
published version and preview `yoke workflows item migrate PREFIX-N
--version N --preview` before applying the migration and retrying the
amendment. This requires a live steering seat covering the target project or document; workers cannot
self-authorize it. `yoke workflows item-posture amend --help` carries the
recovery decision tree. Publishing a definition never blanket-repins items.

The override applies once to an automatic stage default: shift first, then
clamp to the named bounds and the project's level range. An explicit
`--level` or exact surface/model request wins for that launch and bypasses
the item default. Changing an override never changes a running worker.

## Stage levels

Each workflow stage may declare `level`, naming an execution level. Every
non-terminal stage of the shipped workflows defaults to `SENIOR`; terminal
stages carry no level. New immutable versions carry these defaults; existing
item pins and historical definitions stay unchanged. The Workflows stage
strip shows the level glyph and name below the checks.

An item's effective level is its stage level plus the override's `shift`,
clamped to `min` and `max` and the project's lowest and highest available
levels. The item page shows the effective level after Status, its stage
default, and the override and reason in Execution posture. Clearing the
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
   successor after release; other workers and in-flight launches still block.
4. Verify the launch was accepted, then end the session. A refusal names its
   recovery: report it to steering and preserve the checkpoint; do not claim
   success or continue at the previous level. If the predecessor dies before
   launching, steering staffs the now-unclaimed item normally.

The successor reads the Progress Log and the preserved lane's status and log
before acting, then resumes from the checkpoint. The handoff is runtime
staffing, not an operator execution instruction or a workflow skill binding.

## Launching by level

A create with no selector uses the item's live effective stage level, and
Yoke chooses the option and machine. An explicit `--level` overrides one
launch. A missing stage level without an explicit selector refuses as
`stage_level_missing`, naming `--level` or the steering-seat workflow migration
preview/apply prerequisite for an existing old pin. Select a compatible
published version; new versions never move existing pins automatically:

```text
yoke session-control launch preview --project P --level SENIOR [--machine M] --json
yoke session-control launch create --project P --item PREFIX-N --idempotency-key K
```

Placement weighs every option of the level on every machine the caller may
use that offers its surface and has lane capacity. Each option is read
against **only the quota pools its model draws on**: a Claude model draws on
the rolling 5-hour window, the weekly all-models window, and the weekly
window scoped to its own family; a Cursor model draws on Cursor Models or on
Other Models; Codex meters the whole account weekly. Then:

1. **Spread.** An option on a surface with no live worker (or
   launch in flight) and more than 100% headroom wins first, so quota that
   cannot run out before its reset is put to work.
2. **Most headroom.** Otherwise the option with the most headroom on its
   binding pool wins; an option whose pools publish no readable meter ranks
   below every readable one.
3. **Order** — the level's option order, then machine id — breaks ties.

An option is blocked on a machine only by a readable pool with no quota
left; an unreadable or missing meter is unknown, never exhaustion. A Cursor
option's `fallback` is weighed only where the option's own pool is
exhausted. When no option can launch anywhere the launch refuses as
`level_no_capacity`, naming each option and the pool or eligibility rule
that blocked it. Yoke never moves a launch to another level; relaunch at a
different `--level` or wait for the named reset. An unknown level refuses as
`level_unknown` with the levels the project reads.

The launch result and `launch get` name the level, the chosen option, every
pool each option read, and why the winner won (`level_placement`); the
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

Every glyph Yoke stores renders inside fixed-width board columns, so one
contract (`yoke_contracts.glyph_contract`) governs all of them: exactly one
`Emoji_Presentation=Yes` code point (Unicode category `So`, East Asian Width
`W`), with no variation selector, skin-tone modifier, ZWJ, flag, keycap, or
combining mark. Each writer validates at write time and refuses an unsafe
glyph by name — quoting the offending code point and offering safe examples
such as 🐎 or 🚀 — rather than silently stripping it:

| Stored glyph | Writer | Correction command |
|---|---|---|
| Universe level glyph, `levels[N].glyph` | `universe.levels.set` | `yoke universe levels get --json`, correct the glyph, then `yoke universe levels set --stdin` |
| Project override level glyph, `levels[N].glyph` | `session-routing` capability settings | `yoke projects capability-settings set --project P --cap-type session-routing --settings-json '{"levels": [...]}' --base AS_READ_JSON` |
| Project emoji, `projects.emoji` (empty clears it) | `projects.create` / `projects.update` | `yoke projects update --slug S --name N --emoji <glyph>` |
| Workflow stage glyph, `stages[].glyph` | Workflow version publish | Publish an edited definition with `yoke workflows version publish WORKFLOW --definition-file F --expected-current-version N --reason TEXT` (`--keep-current` preserves the global default), then `yoke workflows item migrate ITEM --version V` |

`HC-stored-glyph-contract` FAILs on every stored value that breaks the
contract and prints its location with the correction command above.

## Session labeling

A session is stamped once, at registration, with the lowest level holding an
option that matches it:

1. an explicit level the caller supplied (a deliberate operator re-route)
   wins;
2. otherwise an option on the session's harness family with the session's
   exact model **and** effort;
3. otherwise an option on the session's harness family with its exact model
   (effort unknown, or one no option lists);
4. otherwise the session stays unresolved (`primary`), shown as a warning.

Harness family means any surface of the same harness: a `claude-desktop`
session matches a `claude-cli` option. A fallback selection labels its
option's level. The model matched is the provider-attested model when one
exists, else the requested model with its context-tier suffix (`[1m]`)
removed; the effort is the attested effort, else the requested one.

A level is stamped once, so an edit reaches only sessions that register after
it; a live session is never silently relabeled.

## Stored settings convergence

Levels replaced three older `session-routing` keys — declared level
metadata, selector rules, and harness defaults. Boot removes them from every
stored project document through the ordered migration history and deletes a
document left without levels, so every project reads the universe levels
unless it holds a real override. A write that still uses a retired key is
refused as `level_routing_keys_retired` with the override recipe above.

Machine config carries no launch routing either. A machine file that still
holds a retired launch-default key keeps loading; `yoke status` warns
`machine_config_key_retired` naming each one, and the next config write
removes it.
