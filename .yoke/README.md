# Yoke Project Contract

This directory is the Yoke project contract for Yoke itself. Yoke is
a Yoke-managed project here, not an exception to the project-local contract.
Product source still lives in `runtime/`, `packs/`, `docs`, `.agents/`,
`.claude/`, and `.codex/`; this directory is repo-local appearance and
runbook material.

Yoke execution truth lives in the authoritative Postgres control plane:
project capabilities, provider settings, deployment flows, command
definitions, event evidence, and migration state. This directory explains
that truth for humans without duplicating it as editable runtime state.

## Files

- `lint-config` - hook guard policy in the line-oriented Yoke format.
- `file-line-exceptions` - repo-relative globs for files exempt from the
  local authored-file line limit.
- `labels` - GitHub label color policy in `label_color_*=HEX` format.
- `board.json` - board renderer appearance/tuning knobs.
- `board-art` - live board header art read by the renderer.
- `test-inventory.md` - Yoke test surfaces and lifecycle placement.
- `packs.json` - project-owned receipt for separately updateable Packs; it
  records installed baselines without policing project customizations.
- `runbooks/` - re-seedable scaffolds for project runbooks. Yoke's own
  operational runbooks (deploy, recovery, checklists) live in the
  operator's private ops repo, not in this tree.
- `strategy/` - untracked rendered strategy-doc views (MISSION, VISION,
  MASTER-PLAN, ...). A separate ownership class from the seeded contract
  files: the per-project `strategy_docs` DB rows are authoritative,
  `yoke strategy render` is the only writer, operator edits flow back via
  `yoke strategy ingest` (compare-and-swap), refresh overwrites clean
  renders, and uninstall never removes them. Ignored by git, like the
  generated `BOARD.md`.

For external projects, `yoke project install` seeds this contract
(`seed_if_missing`: project edits always survive refresh; delete a file and
refresh recreates it at current defaults). The generic seed content —
including the starter board art — renders from Python
(`yoke_core.domain.project_contract`), not from copies of Yoke's files.

## What lives where

- Project appearance and repo-owned policy files (this directory):
  `board.json`, `board-art`, `lint-config`, `file-line-exceptions`, `labels`.
- Shared project behavior (authoritative DB): `project-policy` capability
  settings such as `base_branch`, `wip_cap`, `default_priority`,
  `merge_conflict_threshold`, `max_attempts`, and `file_line_limit`.
- Session routing (authoritative DB): `session-routing` capability settings
  for default lanes, lane allowlists, and `/yoke do` process-offer policy.
- Machine view binding (`~/.yoke/config.json`): `projects[<checkout>].board`
  carries `scope` and `render_path` - per-machine, because one machine may
  render this checkout's board with `scope="all"`.
- Generated board view: written to the path machine config resolves
  (default `.yoke/BOARD.md`). Generated output - never edit it, and it
  is never an installed file.

## Boundaries

Do not add credentials, active environment bindings, local databases, backup
directories, scratch/session directories, QA capture folders, install
manifests, generated runtime trees, or project-local Ouroboros exports here.

Generated non-secret summaries may eventually live under `.yoke/generated/`,
but generated summaries are not part of v0 and are never mutation authority.
