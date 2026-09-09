# Session lane routing

Which lane a registering session lands on, and which actions that lane
may run. The offer contract that consumes the resolved lane is
[`session-offer.md`](session-offer.md).

## Resolution

A project declares its lanes in the `session-routing` capability and decides
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
never silently re-routed. A lane's allowed actions are read fresh on every
session offer, so an allowlist edit reaches an already-registered session at
its next offer, with no re-registration.

Editing is a harness job through the existing capability commands:

```text
yoke projects capability-settings get --project NAME --cap-type session-routing
yoke projects capability-settings merge --project NAME --cap-type session-routing --set '<key.path>=<value>'
```

Read the composed result — effective labels and glyphs, selectors per lane,
allowed actions, harness defaults, and any harness that routes nowhere —
with `yoke projects lane-summary get --project NAME`. That same read backs
the read-only lane summary on the Project settings screen.

Lane glyphs are validated at write time against the board's own convention:
one `Emoji_Presentation=Yes` code point, no variation selector, no skin-tone
modifier, no ZWJ/flag/keycap sequence. An unsafe glyph is refused by name
rather than silently stripped.
