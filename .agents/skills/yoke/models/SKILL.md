---
name: models
description: Take Yoke's newer model catalog and levels, or research and publish your own catalog override, then propose the level changes it implies.
argument-hint: "lookup MODEL_ID | get | validate | diff | publish | revisions | restore | follow-shipped | level-proposal"
---

# /yoke models

Reads need no item; an override without a claimed item files `/yoke dash` first.
Yoke updates bring a newer catalog and levels on their own unless you override them.

1. `yoke update --check --json`: a newer catalog and levels arrive with the update.
2. `yoke models revisions` and `yoke settings get levels --json`. Where either
   shows `shipped_defaults_differ`, offer Yoke's defaults: `yoke models
   follow-shipped` (catalog) and `yoke settings unset levels` (levels); clear a
   project override (`yoke projects level-summary get`) as its help says.
3. To override instead, research official provider pages; unknown values stay null.
4. Build the full catalog from the latest revision; validate, diff.
5. An org admin publishes on the diff's `base_revision_id`, effective now or
   later. The override stops following Yoke updates until `follow-shipped`.
6. Propose levels.
7. Record the revision and approved levels in the item's Progress Log; close out through Dash.

Phase map: step 6 reads [level-proposals.md](level-proposals.md).

```text
yoke models publish --stdin --expected-base REV --source-note 'official sources checked YYYY-MM-DD' --json < candidate.json
```
