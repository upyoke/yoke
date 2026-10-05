# /yoke steer — choosing a model for a launch

Every `session_control.launch.create` chooses a supported model selection.
Effort and context are optional and must be supported by that model. This file
is how the steering seat decides what to name. It applies to
**new launches only** — a running session keeps the selection it started with,
and replacing a worker's model means launching a replacement, never editing a
live one.

## Choose for the current leg

Judge the work remaining at the item's live stage, not just its title or the
model that started it. Use the strongest supported models for definition
(idea, refine, shepherd) and pre-merge review/polish. Use cheaper models for
well-specified implementation and mechanical edits. The task, supported
reasoning, cost/benefit, and applicable quota decide; do not always launch
`preferred_session_models`.

| The current leg is | Default tier | At effort |
|---|---|---|
| Definition (idea, refine, shepherd), pre-merge review/polish | tier 1 | `high` |
| Well-specified implementation, simple edits, documentation, routine cleanup | tier 2 | `medium` |
| Difficult debugging or architectural decisions | tier 1 | the surface's step above `high` |

When the remaining work becomes mechanical, downshift the next leg onto a
cheaper supported model. That can be the next leg of the same item: use the
restaff recipe below rather than waiting for a new item. These are staffing
judgments, not static per-skill lane routing or formal per-stage floors.

The ceiling is deliberate. `max` is never an automatic choice: buying the
vendor's highest level for work that does not need it changes nothing about
the outcome and empties a shared allowance faster.

**The debugging row's effort is per surface, and the surface you are launching
answers it — not this table.** Each harness publishes its own accepted
efforts, and a name one surface publishes is refused by another: asking
`codex-cli` for `xhigh` is the step above `high`, while asking `claude-cli`
for it is refused by name (`claude_reasoning_effort_unsupported`) because
that surface's ladder steps straight from `high` to `max`. Read the accepted
list for the surface and pick its next step above `high`; where no such step
is published, ask for `high`:

```text
yoke session-control launch create --project {_project} --surface {_surface} --list-models
```

That prints nothing and launches nothing — it reports the operator's routing
default for the surface plus the efforts and context windows the CLI accepts
for it. The manifest `session_control.launch_model_selection` at
`runtime/harness/<harness-dir>/manifest.json` is the fact it reads; never
restate one of those lists here, because a refreshed manifest would leave
this file teaching a ladder the surface no longer has.

Tiers are **global capability**, not a provider product ladder and not the
best model a harness happens to offer. Tier 1 is the absolute frontier
across providers. Tier 2 is the band immediately below it. Anything under
that band is excluded — not an extra usable rank. A vendor flagship label,
a larger version number, or being the best a harness offers is not evidence
of a tier.

Which models sit in each band today is the model catalog's answer, not this
file's: read the revision with `yoke models get`, or one model's tier with
`yoke models lookup <model-id>`. Naming them here duplicates a value the
catalog owns, so the next reclassification would leave this prose teaching a
tier the catalog has already moved.

On this installation, `claude-cli` and `codex-cli` set `worker_tier` to
`tier2`. Their new worker launches use the models named by the operator's
`tier2` routing keys for all three work kinds — whichever models those keys
name, never an excluded one. Steering may use tier 1, and
an explicit operator request for tier 1 or a specific tier-1 model is
direct authorization for that launch. If the configured tier-2 model is
unavailable, report that fact; never promote silently. Cursor has no
worker-tier override and keeps the Grok-first policy below.

## Which model each tier means

The operator's per-surface routing preference answers that, in
`~/.yoke/config.json`. **The block below is a shape example only — every
model id in it is a placeholder, not a current route.** The live routing
default for a surface is printed by the same `--list-models` read above,
and a model's live tier by `yoke models lookup <model-id>`; a catalog
refresh does not rewrite operator routing or move already-started
sessions:

```json
"session_model_routing": {
  "<surface-id>": {
    "tier1": "<a tier1 model id from the catalog>",
    "tier2": "<a tier2 model id from the catalog>",
    "worker_tier": "tier2"
  },
  "<another-surface-id>": {
    "tier2": "<a tier2 model id from the catalog>",
    "excluded": ["<a model id never to launch>"],
    "fallbacks": ["<a model id the preferred one may hand off to>"]
  }
}
```

Models named in the routing policy's `excluded` list are never launched.
The catalog's `proposed_tier` is advisory and does not override a named
operator route, so an operator may keep routing a model the catalog has
since moved out of that tier. `fallbacks` are
the only models a preferred model may hand off to, and only under the rule
below. A surface with no entry keeps whatever per-surface default it already
had — blank is a
complete answer, not a gap to fill. Cursor omits `tier1` because it has none.

`yoke models lookup MODEL_ID` reads the active sourced catalog revision.
`/yoke models` reviews and publishes revisions without a code change.
Native availability and per-model reasoning efforts remain live surface
observations; the catalog does not decide whether a model can launch.

Effort levels come from what the specific **model** publishes, which can be
narrower than what the surface accepts. Read the model's own
`reasoning_efforts` from native availability; asking for a level a model never
offered is a launch the vendor rejects.

For Cursor, use the exact selector from that machine's native listing, such
as `cursor-grok-4.6-high`, and omit a separate effort when the selector already
names it. A matching separate effort is accepted once; a conflicting effort
is refused. A base name plus effort resolves only to an advertised variant,
never an invented bracket override. Preview shows both the requested name
and the resolved selector that the relay will pass to Cursor.

Omit `--context-window` unless the exact variant's native description names
that window. Grok's listing does not establish 1M support. Some Claude/GPT
variants on Cursor name 1M; preview can select those exact variants for an
explicit 1M request. This is selectable-model evidence, not an observation of
the running session's context. An absent or unattested window remains unknown.
If availability is unknown, refresh it with `yoke relay probe-models --surface
cursor-cli` on the target machine, then preview again. A stale reading retains
the models previously observed and remains visibly stale.

## Cursor: Grok first, Opus only on a confirmed empty pool

Cursor bills two included pools at once. `cursor-grok-*` and `composer-*`
selections draw on **Cursor Models**; everything else draws on **Other
Models**. Whatever the catalog's current tier for each Grok release, the
approved routing keeps a Grok the ordinary Cursor worker — read which one
from the surface's `--list-models` default. Opus on Cursor is a fallback
and nothing else.

Reach for the fallback only when the **Cursor Models** pool is confirmed
empty. Three things that are not confirmation:

- Plenty of headroom in **Other Models**. That is a different allowance; it
  says nothing about the one Grok draws on.
- An unreadable, stale, or errored meter. Unknown is not exhaustion, and
  treating it as one quietly moves spend onto an allowance nobody chose.
- A low **headroom** number. Headroom is remaining runway over time-to-reset
  and can read low while quota remains.

What confirms it is the pool's own quota reading at zero. `launch preview`
reports it per machine under `REQUESTED MODEL POOL`, keyed to the model you
asked for:

```text
yoke session-control launch preview --project P --surface cursor-cli \
  --model cursor-grok-4.6-high --json
```

`Cursor Models: exhausted` is the fallback's trigger. `Cursor Models: 62% left`,
`Cursor Models: unreadable`, and `Cursor Models: no meter` are all "keep asking
for Grok". If you cannot tell the pool apart from the meters that exist, say so
to the operator rather than guessing — that gap is a reporting defect worth a
field-note, not a reason to switch models.

The same rule generalizes: the pool a launch is judged against is always the
one the **requested model** bills to. `HEADROOM` on the preview now names that
window too, so a Grok launch is ranked against Cursor Models rather than
against whichever pool happened to publish the lower number.

## Adopting a new model

Availability is observed natively, so a new flagship family appears the moment
the surface publishes it — no research is required first, and missing research
never gates a launch.

- **Follow the vendor's own replacement metadata.** A model entry's
  `replaced_by` names its successor. Adopt a successor into **tier1 only
  when it is frontier-equivalent** to current Fable/Astra. Never infer a
  rank from a name, a version number, a price, or "this harness's new
  flagship."
- **Re-evaluate the prior family.** A successor does not leave the old
  model in tier1/tier2 just because a vendor still labels it flagship.
- **Classify provisionally when research is behind.** A reliable provider
  description is enough to place a new family under the standing global
  tier policy until the researched reference catches up. Mark it as
  provisional when you record the decision.
- **Operator preference outranks a proposed tier.** The researched
  reference proposes; the operator's `session_model_routing` decides.
  That is still a per-launch judgment, not a blanket default.

## Retry once, then restaff the same item

A local implementation or verification failure gets one retry from the same
worker: diagnose the named failure, correct it, and rerun the failed check.
A second failure, or a spec/design misunderstanding on the first attempt,
gets a fresh session one tier up, seeded from the Progress Log. Do not spend
another retry on a misunderstanding or treat a parked delivery/landing wait
as a failure.

Use rule 9 in [`worker-lifecycle.md`](worker-lifecycle.md): read or request the
checkpoint, terminate the predecessor, verify its claim is released, preview
and launch the successor on the same item at its current stage, then confirm
registration and claim ownership. The checkpoint names the live stage,
committed and uncommitted work, the failure evidence or misunderstanding, and
the next concrete step. The successor reads it and the preserved lane before
acting; it continues the item rather than repeating completed legs.

Choose the next stronger catalog tier within the supported routing and quota
limits above. If the worker is already at tier 1, or no stronger authorized
model is available, report that ceiling and the failure evidence to the
operator for a decision; do not invent a higher tier or promote silently.
Use the same handoff when downshifting the next mechanical leg.

A native resume retains that session's attested selection: Claude restores
it, and Codex and Cursor re-send it. Prefer a pinned version over a mutable
alias. To change the model for the item, launch a successor with a new
selection through restaffing; do not edit the running session's model.
