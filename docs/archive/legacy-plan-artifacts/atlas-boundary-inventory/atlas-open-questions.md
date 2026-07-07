# Atlas open questions

Authored alongside the first Atlas integrity audit (2026-05-27). Each item records an unresolved classification or scope decision the audit surfaced, plus the evidence an operator needs to decide.

## 1. `claims work holder-get`: `--item` flag vs positional `<YOK-N>`

- **Evidence in the audit:** `contradictions[].id = "claims-work-holder-get-flag-vs-positional"`, status `open`. Live `yoke claims work holder-get --help` shows positional `<YOK-N>`; YOK-1847's intent was the `--item YOK-N` flag form to match the wider Yoke CLI grammar.
- **Question:** Should the adapter land the `--item` flag (with positional accepted as a transitional alias), or should we accept the positional form as canonical?
- **Recommended decision:** Land `--item` because it matches the rest of the `claims work` family (`acquire --item`, `release --item`). The positional form can remain as a one-release alias if any live skill recipe depends on it.

## 2. Field-note read surface: agent CLI or operator-debug

- **Evidence in the audit:** `field_notes.read_surface_status = "internal_db_direct"`. The audit reads `ouroboros_entries` directly via `yoke_core.domain.db_helpers` because no `yoke ouroboros field-note list/get` adapter exists today.
- **Question:** Should agents be able to list / fetch their own recent field-notes through the `yoke` CLI? Or is `field-note append` always the only agent-facing operation?
- **Recommended decision:** Add `yoke ouroboros field-note list --limit N --since DATE --agent NAME` and `yoke ouroboros field-note get <id>`. Agents already write notes; letting them inspect their own recent notes closes the loop and removes the operator-debug fallback the audit currently flags as a gap.

## 3. Lint field-note footer detection

- **Evidence in the audit:** `lints.with_field_note_reference = 0 / 60`. Static substring search for the footer text matches nothing, but operator inspection confirms most lint denial messages do emit the footer at runtime (it is injected by `yoke_contracts.field_note_text.FOOTER`).
- **Question:** Should the audit tighten its detector to honour the injected footer (e.g., look for `field_note_text.FOOTER` references), or should the audit accept that this is runtime-only and stop reporting on it?
- **Recommended decision:** Tighten the detector. Looking for any of `field_note_text`, `FIELD_NOTE_FOOTER`, or the `yoke_contracts.field_note_text` module name as imported references will catch the canonical footer-injection sites without false negatives.

## 4. Workspace authority on per-date audit reports

- **Evidence in the audit:** `atlas_integrity_audit.write_report` calls `assert_target_under_session_work_authority`. Per-date reports land under `projects/yoke/qa-artifacts/1685/atlas-integrity-YYYY-MM-DD/report.json`, which is untracked scratch.
- **Question:** Should the workspace authority guard tolerate per-date scratch dirs without requiring path-claim coverage? The current guard already allows free-path locations (`/tmp`, `/var/folders/...`); `projects/yoke/qa-artifacts/` is untracked but inside the worktree.
- **Recommended decision:** Status quo. The guard reads work-claims and allows targets under the claimed worktree by virtue of the worktree path being covered. No carve-out needed.

## 5. Wrapped roster join: tracker vs CLI registry

- **Evidence in the audit:** Section 2 of `docs/atlas.md` is driven directly from `yoke_cli.rows` (the subcommand registry), while `operation_tracker.rows` records the disposition of each known operation surface. Wrapped tracker rows use the same `yoke ...` shell form as the CLI registry.
- **Question:** Should the hard-fact HC compare exact wrapped forms, or is count parity enough?
- **Recommended decision:** Compare exact wrapped forms. Count parity is still useful as a summary, but an exact set check catches one-for-one drift where one wrapped row disappears and an unrelated adapter appears.

## 6. Atlas dashboard / trend lines

- **Evidence in the audit:** Each run produces one JSON snapshot. Trend information (pending count over time, contradiction count decreasing as cutovers land) requires reading multiple snapshots.
- **Question:** Should the renderer or a sibling tool produce a trend view? Or is the cutover progress visible enough through `pending` counts in the rendered Atlas?
- **Recommended decision:** Defer. One snapshot is enough until YOK-1685 lands and the next 2–3 Stage 2 slices run. Revisit when there's history to trend against.
