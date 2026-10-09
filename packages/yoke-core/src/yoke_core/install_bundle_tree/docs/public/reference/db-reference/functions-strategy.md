# Strategy document function calls

Strategy documents are DB-authoritative rows. `yoke strategy` commands dispatch
typed function calls; `.yoke/strategy/` is their gitignored rendered view.

Every content write validates exactly one Summary and one State section. Each
contains a non-empty, trimmed plain-text line. The limits have one owner:
`SUMMARY_MAX_CHARS` and `STATE_MAX_CHARS` in
`yoke_contracts.project_contract.strategy_doc_fields`. Each command's `--help`
prints their numeric limits and the normalized `## Summary (... chars max)`
and `## State (... chars max)` headings. State is authored free text.
Character counts use Unicode characters, not UTF-8 bytes.

| Function | Registered CLI | Contract |
| --- | --- | --- |
| `strategy.doc.create` | `yoke strategy doc create SLUG --summary TEXT --state TEXT --content-file PATH --target-root PATH` | Both fields are required separate payload fields. They replace body copies and are inserted immediately after the first H1, or at the top when no H1 exists. `replaced_body_fields` reports replacements. |
| `strategy.doc.replace` | `yoke strategy doc replace SLUG --content-file PATH --base-updated-at TS --target-root PATH` | Validate both fields before the CAS write. |
| `strategy.doc.section_replace` | `yoke strategy doc section-replace SLUG --heading Summary --content-file PATH --base-updated-at TS --target-root PATH` | Bare field names and numeric limit suffixes match case-insensitively. The complete resulting document must validate. |
| `strategy.ingest.run` | `yoke strategy ingest SLUG --target-root PATH --dry-run` | Validate and normalize each proposed document before any batch write; retain the rendered header's CAS base. |
| `strategy.revision.restore` | `yoke strategy revision restore SLUG --revision N --base-updated-at TS [--summary TEXT] [--state TEXT]` | Historical content must validate. Optional field overrides repair legacy missing or invalid fields before restore. |
| `strategy.seed_defaults.run` | `yoke strategy seed-defaults --project P` | Missing default documents contain valid bounded fields, including for long project display names. |
| `strategy.coordination.append` | `yoke strategy coordination append SLUG --section NAME --entry TEXT` | Summary and State refuse append; use full replacement or section replacement. Other sections append only when the complete document validates. |

Missing, duplicate, empty, multiline, or over-limit fields refuse before the
row or revision history changes. Refusals name the field, observed character
count, limit, and repair. Legacy bare headings and headings with any numeric
`(N chars max)` suffix normalize on the next successful write.

Read projections display the complete valid Summary and preserve State's
authored case and wording. Defensive fallback summaries use the shared limit.
Archived documents retain their stored content until explicitly edited.

Single-document writes print the mutation receipt and render status for the
edited slug only. Refusals and warnings retain their reason and recovery;
`--json` retains the complete mutation envelope.
