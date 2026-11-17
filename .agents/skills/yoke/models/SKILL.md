---
name: models
description: Research and publish effective-dated model catalog revisions, then propose the level changes they imply.
argument-hint: "lookup MODEL_ID | get | validate | diff | publish | revisions | restore | level-proposal"
---

# /yoke models

Reads need no item; a refresh without a claimed item files `/yoke dash` first.

1. `yoke update --check --json`: shipped levels arrive with the server release.
   If `yoke settings get levels --json` shows `shipped_defaults_differ`, offer
   `yoke settings unset levels`; clear a project override (`yoke projects
   level-summary get`) as its help says.
2. Research official provider pages; unknown values stay null.
3. Build the full catalog from the latest revision; validate, diff.
4. An org admin publishes on the diff's `base_revision_id`, effective now or later,
   then publishes the same records to stage (`yoke --env stage models publish`),
   and the lane copies them into `packages/yoke-contracts/src/yoke_contracts/model_reference_data.json`
   so the shipped catalog a fresh database seeds equals the published one.
5. Propose levels.
6. Record the revision and approved levels in the item's Progress Log; close out through Dash.

Phase map: step 5 reads [level-proposals.md](level-proposals.md).

```text
yoke models publish --stdin --expected-base REV --source-note 'official sources checked YYYY-MM-DD' --json < candidate.json
```
