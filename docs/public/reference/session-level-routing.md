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
result names its `source` (`project`, `universe`, or `default`). The Project
settings screen shows the same read.

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
| Workflow stage glyph, `stages[].glyph` | Workflow version publish | Publish a corrected version through the workflow's source (built-in fixture plus `yoke workflows canon-update apply`, or the owning Pack plus `yoke packs update`), then `yoke workflows item migrate ITEM` |

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
refused as `level_routing_keys_retired` with the override recipe above; the
machine config carries no level routing.
