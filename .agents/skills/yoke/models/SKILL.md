---
name: models
description: Refresh the sourced model reference from public primary sources and validate proposed records.
argument-hint: "lookup MODEL_ID | get | validate"
---

# /yoke models

Refresh the sourced model reference. This is a bounded seed plus a
typed reader, not a catalog, discovery service, or routing policy.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Registered operation authority

| Function id | Target | CLI adapter |
|---|---|---|
| `models.lookup.run` | global; `model_id` | `yoke models lookup MODEL_ID [--json]` |
| `models.get.run` | global; optional `model_id` | `yoke models get [--model-id MODEL_ID] [--json]` |
| `models.validate.run` | global; `record` | `yoke models validate --stdin [--json]` |

Python (preferred for sibling readers):

```text
from yoke_contracts.model_reference import lookup_model_reference, lookup_api_price
lookup = lookup_model_reference("<launch --model string>")
```

Lookup never raises. `researched=False` is the explicit unknown marker.
Missing research is not a discovery, launch, or usage gate.

## What this owns

- Seeded records in `yoke_contracts.model_reference_data` and family modules.
- Reader contract: identity, proposed tier with evidence, API prices,
  published subscription rules, optional benchmarks, source URLs, dates.
- Refresh teaching: research official pages, validate, then edit the seed.

It does **not** own live catalog/discovery, usage/cost capture, or
per-surface routing. Routing lives in steering `session_model_routing`.
`proposed_tier` is a researched classification, not an operator launch
table. Optional `operator_notes` is annotation only. There is no
`operator_preferences` field.

## Operator routing (annotation, not published facts)

Persist operator policy in `operator_notes` and in steering routing.
Do not write it into `proposed_tier`, prices, or benchmarks.

Approved 2026-09-07, future launches only (do not change an already-started
session):

1. Simple edits, documentation, routine cleanup: tier2 + medium.
2. Normal development, research, steering: tier1 + high.
3. Difficult debugging or architectural decisions: tier1 + xhigh.
   Where xhigh is unsupported, use high. Resolve supported levels from
   the actual per-model/native surface facts.

Cursor: Grok 4.6 first. Cursor Opus is fallback only after **confirmed**
Grok/Cursor Models quota exhaustion. Unknown, stale, or error is not
exhaustion. Native request string is `cursor-grok-4.6-high`.

## Refresh steps

1. Read official primary sources (provider pricing pages, Cursor model
   docs). Do not assume API dollars equal subscription percentages.
   Distinguish published multipliers from estimates; leave unpublished
   conversion unknown.
2. Do not infer tier from release date or price alone. Do not exclude
   Sonnet from a blanket "use stronger models at lower reasoning" claim.
3. Unknown leaves stay null or empty. Benchmarks stay empty until a
   named public result is attached. No composite quality score.
4. Validate the proposed record:

```bash
printf '%s' '{"model_id":"...","provider":"..."}' | yoke models validate --stdin --json
```

5. Edit the matching seed module under `yoke_contracts/`, keep each file
   under the authored-file line cap, and commit. No paid probes, no
   automatic performance experiments, no broad updater framework.
