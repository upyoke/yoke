# Session level routing

Execution levels are named groupings of harnesses and models. A project can
group its sessions by model tier or harness without changing workflow
settings. Levels carry identity and presentation; workflow bindings select
stage skills, and steering or explicit operator staffing assigns work.

Execution levels are distinct from the claimed worktree lanes that isolate
code changes. See [worktree lanes and claims](agent-rules/lanes-and-claims.md).

## Resolution

A project declares level identities, labels, and optional glyphs in
`level_metadata` on its `session-routing` capability and decides
which session lands on which one. Two surfaces answer that, and the narrower
one wins:

- **`level_rules`** — an optional list of selectors, each naming a level and
  matching on `harness`, on `model`, or on both. A harness value is a
  canonical harness id; surface aliases (`claude-cli`) resolve to their
  family before matching. A model value is either an exact identifier or a
  trailing-star family prefix (`claude-opus-*`).
- **`executor_default_levels`** — the harness default beneath the rules,
  resolved as exact key (`executor_default_level_claude_vscode`) -> wildcard
  key with the longest non-wildcard prefix (`executor_default_level_claude*`)
  -> global `executor_default_level_unknown` -> the unresolved sentinel.

Precedence, most specific first:

1. an explicit level the caller supplied (a deliberate operator re-route);
2. `level_rules` matching harness **and** model;
3. `level_rules` matching model alone;
4. `level_rules` matching harness alone;
5. the `executor_default_levels` harness default.

Within a tier an exact model identifier outranks a trailing-star prefix, and
a longer prefix outranks a shorter one. **Row order never affects the
answer**: two entries that would tie carry the same selector, which the
settings validator refuses.

The model matched is the provider-attested `model` when one exists, and the
`requested_model` (with its context-tier suffix removed) otherwise, because
the level is stamped at registration and the attestation is read back after.
A session with neither matches only the harness tiers — model selectors do
not apply to a model nobody stated.

**When an edit takes effect.** A level is stamped once, at registration, so a
routing edit reaches only sessions that register after it; a live session is
never silently re-routed. Work assignment uses pinned workflow bindings and explicit staffing.

Editing is a harness job through the existing capability commands:

```text
yoke projects capability-settings get --project NAME --cap-type session-routing
yoke projects capability-settings merge --project NAME --cap-type session-routing --set '<key.path>=<value>'
```

Read the composed result — effective labels and glyphs, selectors per level,
harness defaults, and any harness with no configured grouping —
with `yoke projects level-summary get --project NAME`. That same read backs
the read-only level summary on the Project settings screen.

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
| Level glyph, `level_metadata.<LEVEL>.glyph` | `session-routing` capability settings | `yoke projects capability-settings merge --project P --cap-type session-routing --set level_metadata.<LEVEL>.glyph=<glyph>` |
| Project emoji, `projects.emoji` (empty clears it) | `projects.create` / `projects.update` | `yoke projects update --slug S --name N --emoji <glyph>` |
| Workflow stage glyph, `stages[].glyph` | Workflow version publish | Publish a corrected version through the workflow's source (built-in fixture plus `yoke workflows canon-update apply`, or the owning Pack plus `yoke packs update`), then `yoke workflows item migrate ITEM` |

`HC-stored-glyph-contract` FAILs on every stored value that breaks the
contract and prints its location with the correction command above.


## Stored settings convergence

Boot removes retired action-permission settings from stored routing documents
through the ordered migration history. Levels declared only through those
settings become metadata entries so custom groupings survive. New settings
writes refuse the removed keys and name the correction.

Boot also renames the keys of documents stored before the level rename to
the level keys above, including each rule's target field, and the
`harness_sessions` column every session row stamps is `execution_level`. A
write that still uses a pre-rename key refuses and names the level key that
replaces it.
