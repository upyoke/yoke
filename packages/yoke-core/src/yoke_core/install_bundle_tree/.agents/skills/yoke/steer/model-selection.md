# /yoke steer — choosing a model for a launch

Every `session_control.launch.create` chooses a supported model selection.
Effort and context are optional and must be supported by that model. This file
is how the steering seat decides what to name. It applies to
**new launches only** — a running session keeps the selection it started with,
and replacing a worker's model means launching a replacement, never editing a
live one.

## Three kinds of work, and nothing finer

Judge the item you are about to staff against these three. There is no
complexity field to fill in, no score to compute, and no fourth case.
Do not always launch `preferred_session_models`; the task, supported
reasoning, cost/benefit, and applicable quota still decide.

| The work is | Default tier | At effort |
|---|---|---|
| Simple edits, documentation, routine cleanup | tier 2 | `medium` |
| Normal development or research | tier 1 | `high` |
| Difficult debugging or architectural decisions | tier 1 | `xhigh` |

The ceiling is deliberate. `max` is never an automatic choice: buying the
vendor's highest level for work that does not need it changes nothing about
the outcome and empties a shared allowance faster. Where `xhigh` is not
published for the model you chose, ask for `high` instead.

Tiers are **global capability**, not a provider product ladder and not the
best model a harness happens to offer. Tier 1 is the absolute frontier
(Fable/Astra or equivalent successors). Tier 2 is the band immediately
below (Opus 5.5, GPT-6 Sol, and Grok 4.7). Anything below that — including
Sonnet — is excluded, not ranked. Cursor currently has no tier 1 model;
do not relabel latest Grok as tier 1 because it is Cursor's best offering.

On this installation, `claude-cli` and `codex-cli` set `worker_tier` to
`tier2`. Their new worker launches use the models named by the operator's
`tier2` routing keys for all three work kinds, not Sonnet. Steering may use
tier 1, and
an explicit operator request for tier 1 or a specific tier-1 model is
direct authorization for that launch. If the configured tier-2 model is
unavailable, report that fact; never promote silently. Cursor has no
worker-tier override and keeps the Grok-first policy below.

## Which model each tier means

The operator's per-surface routing preference answers that, in
`~/.yoke/config.json`. The teaching example below preserves the approved
route from September 7. Research now proposes newer tier-2 models, but a
reference refresh does not rewrite operator routing or move already-started
sessions:

```json
"session_model_routing": {
  "claude-cli": {
    "tier1": "claude-fable-5-1",
    "tier2": "claude-opus-5",
    "worker_tier": "tier2"
  },
  "codex-cli": {
    "tier1": "gpt-6-astra",
    "tier2": "gpt-5.6-sol",
    "worker_tier": "tier2"
  },
  "cursor-cli": {
    "tier2": "cursor-grok-4.6-high",
    "excluded": ["cursor-auto"],
    "fallbacks": ["claude-opus-5-thinking-high"]
  }
}
```

Models named in the routing policy's `excluded` list are never launched.
The reference's `proposed_tier` is advisory and does not override a named
operator route, including the retained Grok 4.6 selection. `fallbacks` are
the only models a preferred model may hand off to, and only under the rule
below. A surface with no entry keeps whatever per-surface default it already
had — blank is a
complete answer, not a gap to fill. Cursor omits `tier1` because it has none.

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
Models**. Grok 4.7 is global tier 2; approved routing still makes Grok 4.6
the ordinary Cursor worker. Opus on Cursor is a fallback and nothing else.

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

## Selection survives a resume

Model selection is fixed for the life of a session. Claude restores its own
conversation's selection natively; Codex and Cursor re-send the attested
selection on resume. Either way, do not re-derive a model for a session that
is already running, and prefer a pinned version over a mutable alias so a
resumed session cannot be re-resolved onto something else mid-item.

To move a running worker onto a different model, launch a new session for the
next item. Do not change a live one.
