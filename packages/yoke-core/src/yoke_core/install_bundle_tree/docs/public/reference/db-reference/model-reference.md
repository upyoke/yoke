# Model reference functions

Model reference reads use the catalog revision effective at the requested UTC time; omitted time means now. Publications are complete, immutable snapshots, so a later price change does not alter the revision selected for an earlier session. The bundled catalog seeds an empty database once; subsequent updates use these functions without a code release.

| Function id | Claim | Handler | Result |
|---|---|---|---|
| `models.lookup.run` | None | `yoke_core.domain.handlers.model_reference` | One model, `researched`, `revision_id`, `effective_at` |
| `models.get.run` | None | same handler | Catalog or model plus revision provenance; accepts `at` or `revision_id` |
| `models.validate.run` | None | same handler | Validated record |
| `models.diff.run` | None | `yoke_core.domain.handlers.model_reference_publication` | Complete-catalog diff against the latest scheduled revision |
| `models.revisions.run` | None | same handler | Ordered revision history |
| `models.publish.run` | None | same handler | New revision and diff; org admin, expected base, source note, optional future `effective_at` |
| `models.restore.run` | None | same handler | New revision copied from an earlier revision; same publication guards |
| `models.level_proposal.run` | None | `yoke_core.domain.handlers.model_level_proposal` | Proposed universe levels: generated or authored `changes`, the resulting `levels`, `unverified` options, `unplaced_models`; refuses an option its model's published effort or context window contradicts |

Records hold facts about models only: identity, successor (`replacement_model_id`), published `reasoning_efforts` and `context_window_tokens`, prices, subscription rules, sources. A candidate carrying the retired `proposed_tier`, `tier_evidence`, or `tier_provisional` keys is refused with `tier_classification_retired`. Which model a worker launches is decided by the execution levels; `models.level_proposal.run` proposes level changes and writes nothing, and `universe.levels.set` stores the operator-approved document, refusing the same published-value conflicts.

The `$models` skill teaches source review and CLI recipes. `yoke models <command> --help` gives each payload. Model availability and reasoning levels still come from harness-native discovery.
