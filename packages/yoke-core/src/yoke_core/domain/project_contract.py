"""Project-local ``.yoke`` contract content for ``yoke project install``.

Renders the project-visible ``.yoke`` contract files that
:func:`yoke_core.domain.install_bundle.build_bundle` ships as
``project_contract_files``: policy/appearance files generated from their
owning recognizers (``lint_config.GUARD_CATALOG``,
``label_policy.REPO_LABEL_DEFINITIONS``, ``BoardConfig``) plus
fill-me-in scaffolds (runbooks and test inventory).

Every entry carries ``install_policy="seed_if_missing"``: the installer
writes a file only when absent and never overwrites project edits on
refresh, so these files are project-owned the moment they land.

Machine view binding (board ``scope`` / ``render_path``) deliberately
stays out of these files — it lives in ``~/.yoke/config.json`` under
``projects[<checkout>].board``, because one machine may render a
checkout's board with ``scope="all"``. The generated board view lands
wherever ``machine_config.board_render_path`` resolves (default
``.yoke/BOARD.md``) and is never an installed contract file.
"""

from __future__ import annotations

import json
from dataclasses import MISSING, fields
from typing import Dict, List

from yoke_contracts.board.config import BoardConfig
from yoke_core.domain import lint_config
from yoke_contracts.project_contract.board_art import render_board_art
from yoke_contracts.project_contract.install_policy import (
    FORBIDDEN_CONTRACT_RELATIVE_PATHS,
    SEED_IF_MISSING,
    YOKE_TREE_IGNORED_NAMES,
)
from yoke_contracts.project_contract.deployment_flows import (
    DECLARATION_RELATIVE_PATH,
    EMPTY_DECLARATION_TEXT,
)
from yoke_contracts.project_contract.scaffolds import (
    render_deploy_checklist,
    render_deploy_runbook,
    render_project_config,
    render_recovery_runbook,
    render_test_inventory,
)
from yoke_contracts.project_contract.label_policy import (
    DEFAULT_COLOR_OWNER,
    DEFAULT_COLOR_SOURCE,
    DEFAULT_COLOR_STATUS,
    DEFAULT_COLOR_WORKTREE,
    FROZEN_LABEL_COLOR,
    REPO_LABEL_DEFINITIONS,
)


CONTRACT_DIR = ".yoke"

CATEGORY_PROJECT_POLICY = "project_policy"


def bundle_contract_files(display_name: str) -> List[Dict[str, str]]:
    """Render the ``project_contract_files`` bundle entries for a project."""

    contents = {
        f"{CONTRACT_DIR}/.gitignore": render_yoke_gitignore(),
        f"{CONTRACT_DIR}/README.md": render_readme(display_name),
        f"{CONTRACT_DIR}/project.config": render_project_config(display_name),
        f"{CONTRACT_DIR}/lint-config": lint_config.render_lint_config(),
        f"{CONTRACT_DIR}/labels": render_label_policy(),
        f"{CONTRACT_DIR}/board.json": render_board_config(),
        f"{CONTRACT_DIR}/board-art": render_board_art(display_name),
        DECLARATION_RELATIVE_PATH: EMPTY_DECLARATION_TEXT,
        f"{CONTRACT_DIR}/test-inventory.md": render_test_inventory(display_name),
        f"{CONTRACT_DIR}/runbooks/deploy.md": render_deploy_runbook(display_name),
        f"{CONTRACT_DIR}/runbooks/deploy-checklist.md": (
            render_deploy_checklist(display_name)
        ),
        f"{CONTRACT_DIR}/runbooks/recovery.md": (render_recovery_runbook(display_name)),
    }
    return [
        {
            "path": path,
            "content": content,
            "install_policy": SEED_IF_MISSING,
            "category": CATEGORY_PROJECT_POLICY,
        }
        for path, content in sorted(contents.items())
    ]


def render_yoke_gitignore() -> str:
    """Render `.yoke/.gitignore` — the contract tree owns its ignores.

    Everything under `.yoke/` tracks by default; only the generated
    views and machine-local install/run state listed here stay out.
    """

    lines = [
        "# Yoke-managed ignore policy for the .yoke/ tree (seeded by",
        "# `yoke project install`). Generated views and machine-local",
        "# state never track; every other contract file rides the repo.",
        "# Projects need no root-gitignore `.yoke/*` rules.",
    ]
    lines.extend(YOKE_TREE_IGNORED_NAMES)
    return "\n".join(lines) + "\n"


def render_label_policy() -> str:
    """Render GitHub label color policy as ``label_color_*=HEX`` lines."""

    labels = {
        key: value.upper()
        for _label, key, value, _description in REPO_LABEL_DEFINITIONS
    }
    labels.update(
        {
            "label_color_status": DEFAULT_COLOR_STATUS.upper(),
            "label_color_source": DEFAULT_COLOR_SOURCE.upper(),
            "label_color_owner": DEFAULT_COLOR_OWNER.upper(),
            "label_color_worktree": DEFAULT_COLOR_WORKTREE.upper(),
            "label_color_frozen": FROZEN_LABEL_COLOR.upper(),
        }
    )
    ordered_groups = (
        (
            "Type labels",
            (
                "label_color_type_epic",
                "label_color_type_issue",
                "label_color_type_task",
                "label_color_type_integration_fix",
            ),
        ),
        (
            "Priority labels",
            (
                "label_color_priority_high",
                "label_color_priority_medium",
                "label_color_priority_low",
            ),
        ),
        (
            "Generic dynamic label families",
            (
                "label_color_status",
                "label_color_source",
                "label_color_owner",
                "label_color_worktree",
            ),
        ),
        (
            "Lifecycle and flag labels",
            tuple(k for k in labels if k.startswith("label_color_status_"))
            + ("label_color_blocked", "label_color_frozen"),
        ),
    )
    lines = [
        "# Yoke GitHub label color policy.",
        "# Format: label_color_*=HEX",
        "",
    ]
    emitted: set[str] = set()
    for heading, keys in ordered_groups:
        lines.append(f"# {heading}")
        for key in keys:
            value = labels.get(key)
            if value is None or key in emitted:
                continue
            lines.append(f"{key}={value}")
            emitted.add(key)
        lines.append("")
    for key in sorted(set(labels) - emitted):
        lines.append(f"{key}={labels[key]}")
    return "\n".join(lines).rstrip() + "\n"


def render_board_config() -> str:
    """Render ``.yoke/board.json`` with every recognized renderer knob.

    Source of truth is the ``BoardConfig`` dataclass: every scalar knob
    appears at its default value, so the seeded file renders identically
    to no file at all and doubles as the knob inventory. The parser's
    internal catch-all (``rainbow_sub_weights``, the only factory-default
    field) is not a knob and is excluded.
    """

    knobs = {
        field.name: field.default
        for field in fields(BoardConfig)
        if field.default is not MISSING
    }
    # JSON via stdlib follows the machine_config_writer precedent.
    return json.dumps(knobs, indent=2) + "\n"


def render_readme(display_name: str) -> str:
    return f"""# {display_name} Yoke Project Contract

This directory is the Yoke project contract for {display_name}: repo-local
project policy, delivery declarations, and appearance for a Yoke-managed
project. It is not a runtime authority store.

Yoke owns execution truth in its authoritative DB: project capabilities,
provider settings, materialized deployment flows, command definitions, and
event evidence. Project-owned desired configuration in this directory is
materialized into that authority by named commands.

## Files

- `.gitignore` - ignore policy for this tree (generated views and
  machine-local state); root gitignores carry no `.yoke/*` rules.
- `lint-config` - hook guard policy in the line-oriented Yoke format.
- `project.config` - project settings that must be readable with no
  database or network: the authored-file `file_line_limit` and repeated
  `file_line_exception` globs for files exempt from it.
- `labels` - GitHub label color policy in `label_color_*=HEX` format.
- `board.json` - board renderer appearance/tuning; every recognized knob
  at its default value.
- `board-art` - live board header art read by the renderer.
- `deployment-flows.json` - project-owned delivery definitions. Project
  install/refresh additively reconciles declared rows; omitted and historically
  referenced definitions remain in the DB. `retire_if_present` can disable
  known predecessors without creating them on fresh installs.
- `packs.json` - repository-authoritative installed-Pack receipt, created by
  Pack get/update operations. It records versions and merge baselines without
  claiming continuing ownership of the resulting project source.
- `test-inventory.md` - project test surfaces and lifecycle placement.
- `runbooks/` - living deploy/recovery docs; people and agents fill them
  in as the project takes shape.
- `strategy/` - rendered strategy-doc views (untracked local renders).
  A separate ownership class: the Yoke DB `strategy_docs` rows are
  authoritative per project, `yoke strategy render` is the only writer,
  edits flow back via `yoke strategy ingest`, refresh overwrites clean
  renders, and uninstall never removes them.

## Where settings live

Repo-owned project files (this directory; rides the repo):

- `project.config` - on-disk project settings that must be readable with no
  database or network: `file_line_limit` and repeated `file_line_exception`
  globs for the local hook and `yoke check file-line`.
- `board.json` - board renderer knobs, every key at its default.
- `lint-config` - hook guard modes (`<guard>=deny|warn`).
- `labels` - GitHub label colors (`label_color_*=HEX`).
- `deployment-flows.json` - desired flow definitions and optional project
  default; reconcile explicitly with
  `yoke deployment-flows reconcile-project <project>`.
- `packs.json` - installed Pack versions and immutable merge baselines. Pack
  output is ordinary project-owned source; customization is expected and is
  not classified as drift.
- `strategy/` - untracked rendered strategy-doc views (DB-authoritative;
  edit via `yoke strategy ingest`).

DB-owned execution truth and project policy:

- Project row (slug, prefix, breakage policy, repo path):
  `yoke projects get|update --project <project>`.
- Project policy (`project_capabilities.type='project-policy'`): shared
  scalar behavior such as `base_branch`, `wip_cap`, `default_priority`,
  `merge_conflict_threshold`, and `max_attempts`. The authored-file line
  limit is not here — it is checked-in policy in `.yoke/project.config` so
  the offline pre-commit hook can enforce it in a fresh clone.
- Session routing (`project_capabilities.type='session-routing'`): shared
  lane defaults, lane path allowlists, and `/yoke do` process-offer policy.
- Capabilities (`project_capabilities` + `capability_secrets`):
  `yoke projects capability has` and
  `yoke projects capability-secret set`.
- Environments and sites (`environments.settings`, `sites.settings`): model
  desired settings through Project Structure patches or the supported
  project-onboarding surfaces until a dedicated product command exists.
- Project structure families (deployment default, command definitions, merge
  verification, context routing, architecture model):
  `yoke project-structure command-definitions get|list` and
  `yoke project-structure patch apply`.

Machine view binding (`~/.yoke/config.json`): `projects[<checkout>].board`
carries `scope` and `render_path` - per-machine, because one machine may
render this checkout's board with `scope="all"`. The generated board view
lands at the resolved path (default `.yoke/BOARD.md`) - never edit it,
and it is never an installed file.

These files are seeded once by `yoke project install` and never
overwritten on refresh; project edits are preserved. Delete a file and
`yoke project refresh` recreates it at current defaults.

Do not add credentials, active environment bindings, local databases, backup
directories, scratch/session directories, QA capture folders, or generated
runtime trees under this contract.
"""


__all__ = [
    "CATEGORY_PROJECT_POLICY",
    "CONTRACT_DIR",
    "FORBIDDEN_CONTRACT_RELATIVE_PATHS",
    "SEED_IF_MISSING",
    "bundle_contract_files",
    "render_board_art",
    "render_board_config",
    "render_deploy_checklist",
    "render_deploy_runbook",
    "render_project_config",
    "render_label_policy",
    "render_readme",
    "render_recovery_runbook",
    "render_test_inventory",
]
