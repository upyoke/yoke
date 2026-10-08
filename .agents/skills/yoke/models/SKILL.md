---
name: models
description: Research and publish effective-dated model catalog revisions, then propose the level changes they imply.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "lookup MODEL_ID | get | validate | diff | publish | revisions | restore | level-proposal"
---

# /yoke models

Catalog revisions have a UTC `effective_at`. Session cost uses the revision effective
at the session's stored initial `offered_at`, including after reactivation.
Raw usage stays stored. Derived API-equivalent cost is a read-time estimate
shown with its revision ID.

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
| `models.level_proposal.run` | global; optional authored `changes` | `yoke models level-proposal [--stdin] [--levels-only] [--json]` |
| `models.restore.run` | global; source revision, expected base, source note, effective time | `yoke models restore REV --expected-base REV --source-note TEXT [--effective-at UTC] [--json]` |

For an operator or agent, use the registered CLI above. Server-side Python
readers select a DB revision first, then use the pure lookup helper:

```text
from yoke_core.domain.model_reference_store import revision_at
from yoke_contracts.model_reference import lookup_model_reference
revision = revision_at(conn, session_started_at)
lookup = lookup_model_reference("<launch --model string>", revision["records"])
```

Lookup never raises. `researched=False` is the explicit unknown marker.
Missing research is not a discovery, launch, or usage gate.

## What this owns

- Published whole-catalog revisions in `model_reference_revisions`. The bundled
  records bootstrap an empty installation only; refreshing does not edit them.
- Reader contract: identity, successor (`replacement_model_id`), published
  `reasoning_efforts` and `context_window_tokens`, API prices, published
  subscription rules, optional benchmarks, source URLs, dates.
- Refresh teaching: research official pages, validate, diff, publish a
  sourced revision, then propose the level changes the new facts imply.

The catalog holds facts about models only. Which model a worker launches is
decided by the execution levels (`yoke universe levels get`), and nothing
changes a level without operator approval. A record carrying the retired
`proposed_tier`, `tier_evidence`, or `tier_provisional` keys is refused by
name. Optional `operator_notes` is annotation only.

## Proposing level changes

`yoke models level-proposal` reads the current catalog revision and the
universe levels and returns every change it can extrapolate:

- an option whose model the catalog supersedes is retired and its successor
  added at the same position, carrying the option's surface, selector shape,
  effort, and context window;
- an option whose effort or context window the model's published values do
  not include moves to the nearest published effort the surface accepts, or
  to the model's default window.

It also lists `unverified` options (model not researched, or no published
efforts or windows) and `unplaced_models` (catalog models no level launches
and nothing supersedes). Placing an unplaced model, moving an option between
levels, or retiring one is the refresh author's judgment: extrapolate from
where today's options sit and what is known about the new and old models,
then pass the complete change list on `--stdin`, starting from the generated
`changes` in `--json` output. Each change is one of:

```json
{"kind": "add", "level": "SENIOR", "option": {"surface": "...", "model": "...", "reasoning_effort": "...", "context_window_tokens": null}, "position": 0, "reason": "..."}
{"kind": "move", "option": {"surface": "...", "model": "...", "reasoning_effort": "..."}, "to_level": "JUNIOR", "reason": "..."}
{"kind": "retire", "option": {"surface": "...", "model": "...", "reasoning_effort": "..."}, "reason": "..."}
{"kind": "change", "option": {"surface": "...", "model": "...", "reasoning_effort": "..."}, "reasoning_effort": "high", "context_window_tokens": null, "reason": "..."}
```

Any resulting option whose effort or context window its model's published
values contradict is refused by name (`level_option_reasoning_effort_unpublished`,
`level_option_context_window_tokens_unpublished`); `yoke universe levels set`
refuses the same documents. Present the proposal to the operator. Only after
approval, store it:

```bash
yoke models level-proposal --levels-only [--stdin < changes.json] > /tmp/levels.json
yoke universe levels set --stdin < /tmp/levels.json
```

## Dash entry

For a direct refresh request with no claimed work item, file a `/yoke dash`
for the bounded research and publication, then acquire its item work claim.
When repository files change, survey their paths and work in Dash's registered
worktree. For a DB-only refresh, survey `--no-changes`; Dash prepare records
its laneless skip. Keep the candidate JSON in a temp file and its lasting
sources in catalog records and the publication note. Publish through the prod
control plane after review, record the revision in the Progress Log, and use
Dash close-out; a DB-only refresh needs no release. An approved level change
is part of the same DB-only refresh. A claimed item uses its
existing worktree and workflow.
Read-only `lookup`, `get`, `validate`, `diff`, and `revisions` need no Dash.

## Refresh steps

1. Read official primary sources (provider pricing pages, Cursor model
   docs). Do not assume API dollars equal subscription percentages.
   Distinguish published multipliers from estimates; leave unpublished
   conversion unknown.
2. Record each model's published `reasoning_efforts` and
   `context_window_tokens` from the provider's own model page, and set
   `replacement_model_id` on a model the provider supersedes. Observe what
   each surface can launch with `yoke relay probe-models --surface S`.
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

5. Inspect the diff for adds, changes, removals, sources, dates, published
   efforts and context windows, and successors. Publish with the diff's `base_revision_id`. Choose a UTC effective
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
7. Run `yoke models level-proposal`, complete the change list as described
   in "Proposing level changes", and present it to the operator. Store the
   approved levels with `yoke universe levels set --stdin`, then record the
   catalog revision and the level change in the Progress Log.
