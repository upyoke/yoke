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

The `$models` skill teaches source review and CLI recipes. `yoke models <command> --help` gives each payload. Model availability and reasoning levels still come from harness-native discovery, while routing choices remain session policy.
