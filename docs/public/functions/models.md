# Model reference functions

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Functions](index.md) > Models
<!-- /yoke:breadcrumbs -->

Model reference reads use the catalog revision effective at the requested UTC time; omitted time means now. Publications are complete, immutable snapshots, so a later price change does not alter the revision selected for an earlier session. Each revision has a `source`: `shipped` (Yoke's catalog) or `operator` (an override published or restored by an org admin). Every server start appends the running build's shipped catalog while the latest revision is `shipped` and the catalog differs from every shipped revision stored, so an older build never undoes a newer one. An `operator` latest revision is never replaced by a start; reads report `shipped_defaults_differ` until `models.follow_shipped.run` makes the shipped catalog current again.

| Function id | Claim | Handler | Result |
|---|---|---|---|
| `models.lookup.run` | None | `yoke_core.domain.handlers.model_reference` | One model, `researched`, `revision_id`, `effective_at`; `shipped_defaults_differ` while an operator override is latest |
| `models.get.run` | None | same handler | Catalog or model plus revision provenance and `source`; accepts `at` or `revision_id`; `shipped_defaults_differ` while an operator override is latest |
| `models.validate.run` | None | same handler | Validated record |
| `models.diff.run` | None | `yoke_core.domain.handlers.model_reference_publication` | Complete-catalog diff against the latest scheduled revision |
| `models.revisions.run` | None | same handler | Ordered revision history with each `source`; `shipped_defaults_differ` while an operator override is latest |
| `models.publish.run` | None | same handler | New operator revision and diff; org admin, expected base, source note, optional future `effective_at` |
| `models.restore.run` | None | same handler | New operator revision copied from an earlier revision; same publication guards |
| `models.follow_shipped.run` | None | same handler | Org admin; appends the shipped catalog as a `shipped` revision (`appended`, revision, diff), or `appended: false` when already following it |
| `models.level_proposal.run` | None | `yoke_core.domain.handlers.model_level_proposal` | Proposed universe levels: generated or authored `changes`, the resulting `levels`, `unverified` rows, placeable `unplaced_models`, `unplaceable_models` (no published efforts), `equals_shipped_defaults` and the `apply_command` (`reset` when equal to the shipped defaults); refuses a row its model's published effort contradicts |

Records hold facts about models only: identity, successor (`replacement_model_id`), published `reasoning_efforts` and `context_window_tokens`, prices, subscription rules, sources. A candidate carrying the retired `proposed_tier`, `tier_evidence`, or `tier_provisional` keys is refused with `tier_classification_retired`. Which model a worker launches is decided by the execution levels; `models.level_proposal.run` proposes level changes and writes nothing, and `universe.levels.set` stores the operator-approved document, refusing the same published-value conflicts; `universe.levels.reset` returns the universe to shipped defaults.

The `$models` skill teaches source review and CLI recipes. `yoke models <command> --help` gives each payload. Model availability and reasoning levels still come from harness-native discovery.
