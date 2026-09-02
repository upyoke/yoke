"""What the onboard wizard's Apply does to the checkout for board art.

The operator designs the master map and headers before Apply, but the art can
only be written once Apply has materialized the checkout — after
``project install`` has already committed everything the bundle wrote. So this
module owns the whole close-out: write ``.yoke/board-art``, rebuild the initial
``BOARD.md``, commit the art, prove no installer-written path was left
uncommitted, and record what happened on the durable apply report. Without the
commit the operator's first ``git status`` in a brand-new checkout reports the
installer's own output as their uncommitted change.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from yoke_contracts.project_contract.board_art.config_paths import (
    board_art_path_for_config,
)

BOARD_ART_COMMIT_MESSAGE = "Set project board art"
BOARD_ART_STEP_ACTION = "project-write-board-art"


def repo_root_from_report(report: Any, fallback_checkout: str | None) -> Path | None:
    checkout = None
    if isinstance(report, dict):
        onboarding = report.get("project_onboarding")
        if isinstance(onboarding, dict):
            checkout = onboarding.get("checkout")
            if isinstance(checkout, Mapping):
                checkout = checkout.get("path")
    checkout = checkout or fallback_checkout
    if not checkout:
        return None
    return Path(str(checkout)).expanduser()


def board_art_exists(repo_root: str | Path | None) -> bool:
    """Return whether the checkout already has project-local board art."""
    if not repo_root:
        return False
    return board_art_path_for_config(None, repo_root=str(repo_root)).is_file()


def write_board_art(repo_root: Path, word: str, variants: list[Any]) -> None:
    """Write the chosen master map + header variants to ``.yoke/board-art``."""
    from yoke_contracts.project_contract.board_art.config import BLACK, WHITE
    from yoke_contracts.project_contract.board_art.config_paths import (
        board_art_path_for_config,
    )
    from yoke_contracts.project_contract.board_art.render_seed import (
        _ART_HEADER,
        _master_map_lines,
    )

    art_path = board_art_path_for_config(None, repo_root=str(repo_root))
    parts = [
        _ART_HEADER.format(white=WHITE, black=BLACK),
        "## Master Map",
        "",
        "\n".join(_master_map_lines(word)),
    ]
    for variant in variants:
        parts.extend(("", f"## {variant.kind}", "", variant.text.rstrip()))
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


def commit_board_art(
    repo_root: Path, onboarding_report: Any,
) -> dict[str, Any]:
    """Commit the art this run wrote and prove the checkout is clean.

    ``project install`` commits what the bundle wrote and returns; the
    operator's own board art is written afterwards, once the checkout
    exists. Committing it here is what keeps a freshly onboarded checkout
    from being dirty with the installer's own output before its owner has
    touched it, and the assertion refuses to report success when any
    installer-written path is somehow still uncommitted.
    """
    from yoke_cli.project_install import checkout_gate, installed_output_paths

    root = Path(repo_root).expanduser()
    art_rel = str(
        board_art_path_for_config(None, repo_root=str(root)).relative_to(root)
    )
    commit = checkout_gate.commit_paths(
        root, [art_rel], message=BOARD_ART_COMMIT_MESSAGE,
    )
    install = _install_report(onboarding_report)
    verified = [art_rel]
    # An install that did not commit (``--no-commit``, or a checkout git does
    # not own) left its own writes uncommitted on purpose; only the art this
    # step wrote is ours to prove.
    if _install_committed(install):
        verified += installed_output_paths.owned_paths(install)
    return {
        "commit": commit,
        "verified_paths": checkout_gate.assert_paths_committed(
            root, verified,
        ),
    }


def record_board_art_done(
    onboarding_report: Any,
    receipt: Mapping[str, Any],
    *,
    report_path: str | None = None,
) -> dict[str, Any]:
    """Record what the board-art step actually did on the durable receipt.

    The apply report finishes before this step runs, so it marks the step
    done from the write plan alone. Writing the commit and the paths proved
    clean back onto the step is what makes the receipt describe the run.
    """
    from yoke_cli.config import onboard_apply_late_steps

    path = _apply_report_path(onboarding_report) or report_path
    if not path:
        return {}
    commit = receipt.get("commit")
    commit = commit if isinstance(commit, Mapping) else {}
    return onboard_apply_late_steps.complete_report_path(
        path,
        action=BOARD_ART_STEP_ACTION,
        detail={
            "commit_status": str(commit.get("status") or ""),
            "commit_sha": str(commit.get("sha") or ""),
            "committed_paths": list(commit.get("paths") or []),
            "verified_clean_paths": list(receipt.get("verified_paths") or []),
        },
    )


def mark_board_art_failed(
    onboarding_report: Any,
    exc: BaseException,
    *,
    report_path: str | None = None,
    resume_command: str | None = None,
) -> dict[str, Any]:
    """Mark the board-art step failed on the durable receipt."""
    from yoke_cli.config import onboard_apply_late_steps, onboard_apply_report

    path = _apply_report_path(onboarding_report) or report_path
    if not path:
        return {}
    try:
        return onboard_apply_late_steps.fail_report_path(
            path, exc, action=BOARD_ART_STEP_ACTION,
        )
    except Exception:  # noqa: BLE001 - failure screen can still show root cause
        return {
            "path": path,
            "resume_command": (
                resume_command or onboard_apply_report.RESUME_COMMAND
            ),
        }


def _apply_report_path(onboarding_report: Any) -> str | None:
    summary = (
        onboarding_report.get("apply_report")
        if isinstance(onboarding_report, Mapping)
        else None
    )
    if not isinstance(summary, Mapping):
        return None
    return str(summary.get("path") or "") or None


def _install_report(onboarding_report: Any) -> Mapping[str, Any]:
    if not isinstance(onboarding_report, Mapping):
        return {}
    onboarding = onboarding_report.get("project_onboarding")
    if not isinstance(onboarding, Mapping):
        return {}
    install = onboarding.get("install")
    return install if isinstance(install, Mapping) else {}


def _install_committed(install: Mapping[str, Any]) -> bool:
    commit = install.get("commit")
    if not isinstance(commit, Mapping):
        return False
    return str(commit.get("status") or "") in ("created", "nothing_to_commit")


def rebuild_board(repo_root: Path) -> Path:
    """Rebuild the project's initial BOARD.md and return the written path."""
    from yoke_cli.board import rebuild as board_rebuild_flow

    resolved_repo_root = board_rebuild_flow.resolve_main_repo_root(str(repo_root))
    board_path = board_rebuild_flow.resolve_board_path(resolved_repo_root, None)
    result = board_rebuild_flow.rebuild(
        repo_arg=str(resolved_repo_root),
        force=True,
        emit=False,
    )
    if int(result.exit_code) != 0:
        detail = result.message or f"board rebuild exited with {result.exit_code}"
        raise RuntimeError(detail)
    if not board_path.is_file():
        raise RuntimeError(f"board rebuild did not write {board_path}")
    return board_path


__all__ = [
    "BOARD_ART_COMMIT_MESSAGE",
    "BOARD_ART_STEP_ACTION",
    "board_art_exists",
    "commit_board_art",
    "mark_board_art_failed",
    "rebuild_board",
    "record_board_art_done",
    "repo_root_from_report",
    "write_board_art",
]
