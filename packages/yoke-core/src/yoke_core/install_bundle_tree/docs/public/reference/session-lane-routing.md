# Session lane routing

Execution lanes are named groupings of harnesses and models. A project can
group its sessions by model tier or harness without changing workflow
settings. Lanes carry identity and presentation; workflow bindings select
stage skills, and steering or explicit operator staffing assigns work.

Execution lanes are distinct from the claimed worktree lanes that isolate
code changes. See [worktree lanes and claims](agent-rules/lanes-and-claims.md).

## Resolution

A project declares lane identities, labels, and optional glyphs in
`lane_metadata` on its `session-routing` capability and decides
which session lands on which one. Two surfaces answer that, and the narrower
one wins:

- **`lane_rules`** — an optional list of selectors, each naming a lane and
  matching on `harness`, on `model`, or on both. A harness value is a
  canonical harness id; surface aliases (`claude-cli`) resolve to their
  family before matching. A model value is either an exact identifier or a
  trailing-star family prefix (`claude-opus-*`).
- **`executor_default_lanes`** — the harness default beneath the rules,
  resolved as exact key (`executor_default_lane_claude_vscode`) -> wildcard
  key with the longest non-wildcard prefix (`executor_default_lane_claude*`)
  -> global `executor_default_lane_unknown` -> the unresolved sentinel.

Precedence, most specific first:

1. an explicit lane the caller supplied (a deliberate operator re-route);
2. `lane_rules` matching harness **and** model;
3. `lane_rules` matching model alone;
4. `lane_rules` matching harness alone;
5. the `executor_default_lanes` harness default.

Within a tier an exact model identifier outranks a trailing-star prefix, and
a longer prefix outranks a shorter one. **Row order never affects the
answer**: two entries that would tie carry the same selector, which the
settings validator refuses.

The model matched is the provider-attested `model` when one exists, and the
`requested_model` (with its context-tier suffix removed) otherwise, because
the lane is stamped at registration and the attestation is read back after.
A session with neither matches only the harness tiers — model selectors do
not apply to a model nobody stated.

**When an edit takes effect.** A lane is stamped once, at registration, so a
routing edit reaches only sessions that register after it; a live session is
never silently re-routed. Work assignment uses pinned workflow bindings and explicit staffing.

Editing is a harness job through the existing capability commands:

```text
yoke projects capability-settings get --project NAME --cap-type session-routing
yoke projects capability-settings merge --project NAME --cap-type session-routing --set '<key.path>=<value>'
```

Read the composed result — effective labels and glyphs, selectors per lane,
harness defaults, and any harness with no configured grouping —
with `yoke projects lane-summary get --project NAME`. That same read backs
the read-only lane summary on the Project settings screen.

Lane glyphs are validated at write time against the board's own convention:
one `Emoji_Presentation=Yes` code point, no variation selector, no skin-tone
modifier, no ZWJ/flag/keycap sequence. An unsafe glyph is refused by name
rather than silently stripped.


## Stored settings convergence

Boot removes retired action-permission settings from stored routing documents
through the ordered migration history. Lanes declared only through those
settings become metadata entries so custom groupings survive. New settings
writes refuse the removed keys and name the correction.
