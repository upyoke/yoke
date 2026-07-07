# I4C Legacy Config/Local-Shape Audit

Scope: final G3.P1.I4C cleanup evidence for machine config and board config.

## Purged

- Machine config owns machine truth only: connection, credentials, temp/cache
  roots, runtime settings, and checkout path to integer `project_id` mapping.
- Per-checkout project entries no longer carry a duplicated project slug/name.
  Project slug/display data is DB-owned and resolved from `project_id` when a
  label is needed.
- Per-project board render routing remains user-scoped in machine config:
  `projects.<checkout>.board.render_path` and `.scope`.
- Board tuning moved to project-local `.yoke/board.json`: dashboard toggles,
  timeline labeling, section limits, meter cap, and board-art render weights.
- `.yoke/board-art` is art content only. There is no configurable `art_path`;
  the path is fixed next to `.yoke/board.json`.
- `wip_cap`, `strategize_carry_horizon_days`, and `strategize_carry_limit`
  remain machine/runtime policy settings, not board settings.

## Evidence

- `yoke config example` prints the code-owned canonical payload from
  `runtime/api/domain/machine_config_contract.py`: `project_id` plus board
  `render_path`/`scope`, with no project slug/name and no `art_path`.
- `yoke status --json` resolves Yoke as `project_id=1`, `board_scope=all`,
  and Buzz as `project_id=2`, `board_scope=buzz`.
- Active scan for retired repo-bound connected-env paths:
  `rg -n 'data/connected-env\.json|connected-env\.json' runtime docs .yoke`
  returns no live matches.
- Active scan for board/dashboard/timeline/art settings in
  `~/.yoke/config.json` returns no matches; the settings appear in each
  project's `.yoke/board.json`.

## Historical Mentions

Old terms may still appear in archive/audit CSV artifacts under
`docs/archive/**` and older `docs/archive/legacy-plan-artifacts/**` inventories. Those
files are historical evidence, not active reader or operator teaching surfaces.
