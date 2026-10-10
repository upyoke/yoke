---
name: models
description: Research and publish effective-dated model catalog revisions, then propose the level changes they imply.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "lookup MODEL_ID | get | validate | diff | publish | revisions | restore | level-proposal"
---


# /yoke models

Catalog revisions have UTC `effective_at`. Session estimates use the revision
effective at initial stored `offered_at`, including reactivation; raw usage
remains stored, and read-time API-equivalent estimates name the revision.
Bundled records bootstrap empty installations only.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Catalog facts include identity, successor `replacement_model_id`, published
efforts/windows, API prices, subscription rules, optional benchmarks, URLs and
dates. Unknown lookup is `researched=False`, never raises and never gates
discovery, launch or usage. Server readers select `model_reference_store.revision_at`
before pure `lookup_model_reference`. `operator_notes` is annotation;
retired `proposed_tier`, `tier_evidence`, `tier_provisional` keys refuse by name.
Execution levels decide launches, with operator approval for every change.

## Phase map

| Phase | Read before acting |
|---|---|
| Read or refresh facts | Entry and refresh steps below |
| Propose/update levels | [level-proposals.md](level-proposals.md) |

## Entry

Registered function ids and claim policy: [service catalog](../../../../.yoke/docs/reference/db-reference/functions-runtime.md).

Read-only lookup/get/validate/diff/revisions needs no Dash:

```sh
yoke models lookup MODEL_ID [--json]
yoke models get [--model-id MODEL_ID] [--json]
yoke models get --revision-id REV [--json]
yoke models get --at UTC [--json]
yoke models revisions [--json]
```

A direct refresh without a claimed item files bounded `/yoke dash` and acquires
its work claim. Repo changes use path survey and its registered lane; DB-only
uses `--no-changes` survey and prepare's laneless skip. An existing claimed
item keeps its lane/workflow. Candidate JSON stays in a temp file; durable
sources belong in catalog records/publication notes. Review and publish on
prod, record the revision and approved levels in Progress Log, then Dash
close-out. DB-only refresh needs no release; approved level changes share it.

## Refresh

1. Research official provider pricing/model pages and Cursor docs. Record
   published efforts, context windows and successor; observe surface launch
   support with `yoke relay probe-models --surface S`. API dollars do not imply
   subscription percentages; distinguish published multipliers from estimates.
   Unknown conversion/values stay null or empty. Benchmarks need a named public
   result; no composite quality score, paid probes or automatic experiments.
2. Read revisions. Start from the latest scheduled revision with
   `yoke models get --revision-id REV --json`, otherwise current get.
   Prepare the complete catalog preserving unchanged records; validate changed
   records and inspect adds/changes/removals, sources/dates, efforts/windows and
   successors:

   ```sh
   yoke models validate --stdin --json < model-record.json
   yoke models diff --stdin --json < candidate.json
   ```

3. An org admin publishes using the diff's `base_revision_id`, with sourced
   evidence in `--source-note`. Effective time is UTC now/future; past refuses
   to prevent old-session repricing. Base must be latest scheduled revision;
   the new effective time cannot precede it.

   ```sh
   yoke models publish --stdin --expected-base REV --source-note 'official sources checked YYYY-MM-DD' [--effective-at UTC] --json < candidate.json
   yoke models revisions --json
   ```

4. Re-read the published revision to verify content/time. Restore publishes a
   new immutable-history revision copied from the source, with expected current
   base and evidence. Replace a future revision at its effective time or later:

   ```sh
   yoke models restore REV --expected-base CURRENT --source-note 'reason' [--effective-at UTC] --json
   ```

5. Run `yoke models level-proposal`, follow the linked level phase, present
   the complete proposal and obtain approval before `yoke universe levels set`.
   Record both revision and approved level change.
