---
name: models
description: Research, review, and publish effective-dated model catalog revisions.
argument-hint: "lookup MODEL_ID | get | validate | diff | publish | revisions | restore"
---

# /yoke models

Research and publish the sourced model catalog in the control-plane database.
Each complete revision has a UTC `effective_at`. Session cost uses the revision
effective at the session's stored initial `offered_at`, including after
reactivation. Raw usage remains stored; derived API-equivalent cost remains a
read-time estimate, with its revision ID shown beside it.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Registered operation authority

| Function id | Target | CLI adapter |
|---|---|---|
| `models.lookup.run` | global; `model_id` | `yoke models lookup MODEL_ID [--json]` |
| `models.get.run` | global; optional `model_id`, `revision_id`, `at` | `yoke models get [--model-id MODEL_ID] [--revision-id REV \| --at UTC] [--json]` |
| `models.validate.run` | global; `record` | `yoke models validate --stdin [--json]` |
| `models.diff.run` | global; complete `catalog` | `yoke models diff --stdin [--json]` |
| `models.publish.run` | global; complete catalog, expected base, source note, effective time | `yoke models publish --stdin --expected-base REV --source-note TEXT [--effective-at UTC] [--json]` |
| `models.revisions.run` | global | `yoke models revisions [--json]` |
| `models.restore.run` | global; source revision, expected base, source note, effective time | `yoke models restore REV --expected-base REV --source-note TEXT [--effective-at UTC] [--json]` |

For an operator or agent, use the registered CLI above. Server-side Python
readers select a DB revision first, then use the pure lookup helper:

```text
from yoke_core.domain.model_reference_store import revision_at
from yoke_contracts.model_reference import lookup_model_reference
revision = revision_at(conn, session_offered_at)
lookup = lookup_model_reference("<launch --model string>", revision["records"])
```

Lookup never raises. `researched=False` is the explicit unknown marker.
Missing research is not a discovery, launch, or usage gate.

## What this owns

- Published whole-catalog revisions in `model_reference_revisions`. The bundled
  records bootstrap an empty installation only; refreshing does not edit them.
- Reader contract: identity, proposed tier with evidence, API prices,
  published subscription rules, optional benchmarks, source URLs, dates.
- Refresh teaching: research official pages, validate, diff, then publish a
  sourced revision through the registered DB command.

Native selectable models and supported reasoning efforts come from each
surface's live API observations, independently of this research catalog.
Tier-to-model routing lives in machine `session_model_routing`, independently
of catalog revisions. This skill does not change usage capture or routing.
`proposed_tier` is a researched global classification, not an operator
launch table. Optional `operator_notes` is annotation only. There is no
`operator_preferences` field.

## Global tier meaning

Tiers measure capability relative to the **absolute frontier across
providers**, not a vendor's own product ladder and not the best model a
particular harness happens to offer.

- **tier1** — frontier-equivalent families and their successors only
  (currently Fable and Astra). Cursor currently has no tier1 model.
- **tier2** — the band immediately below that frontier (currently Opus
  5.5, GPT-6 Sol, and Grok 4.7).
- **excluded** — below the usable floor for new tier-based steering
  selections (including Sonnet and superseded families). Not an extra
  usable rank. An explicit operator route can still name one.

A vendor flagship label, a larger version number, a higher price, or a
new harness selector is not evidence of global tier1. Re-evaluate older
families on every refresh; do not accumulate them in tier1/tier2 because
they were once flagship. Do not overwrite operator-approved
classifications with generic flagship prose. Keep identities, exact
native selectors, supported reasoning, price, and subscription data
distinct from the classification. Do not fabricate benchmarks or change
pricing as part of a classification correction.

## Operator routing (annotation, not published facts)

Read [steer/model-selection.md](../steer/model-selection.md) for the approved
work-kind, effort, worker-tier, and fallback policy. Operator policy belongs
in `operator_notes` and machine `session_model_routing`, never in sourced
prices, benchmarks, or `proposed_tier`. A catalog refresh does not change
routing or an already-started session.

## Dash entry

For a direct refresh request with no claimed work item, file a `/yoke dash`
for the bounded research and publication, then acquire its item work claim.
When repository files change, survey their paths and work in Dash's registered
worktree. For a DB-only refresh, survey `--no-changes`; Dash prepare records
its laneless skip. Keep the candidate JSON in a temp file and its lasting
sources in catalog records and the publication note. Publish through the prod
control plane after review, record the revision in the Progress Log, and use
Dash close-out; a DB-only refresh needs no release. A claimed item uses its
existing worktree and workflow.
Read-only `lookup`, `get`, `validate`, `diff`, and `revisions` need no Dash.

## Refresh steps

1. Read official primary sources (provider pricing pages, Cursor model
   docs). Do not assume API dollars equal subscription percentages.
   Distinguish published multipliers from estimates; leave unpublished
   conversion unknown.
2. Classify against the global frontier meaning above. Do not infer
   tier from release date, price, version, or "this harness's flagship"
   alone. Re-evaluate prior families instead of retaining their old
   rank. Sonnet stays excluded from ordinary steering selections.
3. Unknown leaves stay null or empty. Benchmarks stay empty until a
   named public result is attached. No composite quality score.
4. Read `yoke models revisions --json`; start from its latest revision with
   `yoke models get --revision-id REV --json` when one is scheduled, otherwise
   use `yoke models get --json`. Prepare the complete candidate JSON; preserve
   unchanged records. Validate
   changed records and review the whole-catalog diff:

```bash
printf '%s' '{"model_id":"...","provider":"..."}' | yoke models validate --stdin --json
yoke models diff --stdin --json < candidate.json
```

5. Inspect the diff for adds, changes, removals, sources, dates, and proposed
   tiers. Publish with the diff's `base_revision_id`. Choose a UTC effective
   time now or in the future; past times are refused so old sessions never
   reprice. A later publication must use the latest scheduled revision as
   its base and cannot take effect before it. `--source-note` records research
   and publication evidence. Publication requires an org admin actor.

```bash
yoke models publish --stdin --expected-base REV --source-note 'official sources checked YYYY-MM-DD' --json < candidate.json
yoke models revisions --json
```

6. Re-read the published revision and confirm its content and effective time.
   To recover, `yoke models restore REV --expected-base CURRENT --source-note
   'reason'` publishes a new revision copied from REV; history is immutable.
   A scheduled future revision must be replaced at its effective time or later.
   No paid probes or automatic performance experiments.
