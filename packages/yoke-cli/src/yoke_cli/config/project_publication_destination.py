"""Yoke-owned checkout publication choice, independent of Git remote config."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts import terminal_detached_process

LEGACY_READ_ONLY_PUSH_URL = "disabled://yoke-read-only"


def push_urls(root: str | Path, remote: str = "origin") -> tuple[str, ...]:
    result = terminal_detached_process.run(
        ["git", "-C", str(root), "remote", "get-url", "--push", "--all", remote],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return tuple(result.stdout.splitlines()) if result.returncode == 0 else ()


def migrate_legacy(root: str | Path, *, config_path=None) -> bool:
    """Persist the legacy origin choice before removing only sentinel entries."""
    from yoke_cli.config import machine_config, writer_projects

    entry = machine_config.project_entry(root, config_path)
    origin_read_only = LEGACY_READ_ONLY_PUSH_URL in push_urls(root)
    if origin_read_only:
        if not entry:
            return True  # Preserve the old guard until setup registers this checkout.
        writer_projects.set_publication_read_only(root, True, path=config_path)
    remotes = terminal_detached_process.run(
        ["git", "-C", str(root), "remote"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    for remote in remotes:
        if LEGACY_READ_ONLY_PUSH_URL in push_urls(root, remote):
            result = terminal_detached_process.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "--local",
                    "--unset-all",
                    f"remote.{remote}.pushurl",
                    "^disabled://yoke-read-only$",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode and LEGACY_READ_ONLY_PUSH_URL in push_urls(
                root, remote
            ):
                raise RuntimeError(
                    "publication_policy_migration_failed: legacy push URL was not removed; retry setup"
                )
    return origin_read_only or entry.get("publication_read_only", False)


def read_only(root: str | Path, remote: str = "origin") -> bool:
    from yoke_cli.config import machine_config

    entry = machine_config.project_entry(root)
    return entry.get("publication_read_only", False) or LEGACY_READ_ONLY_PUSH_URL in push_urls(root)


def recovery(remote: str = "origin") -> str:
    return (
        f"publication_destination_read_only: Yoke publication to {remote} is disabled "
        "by this checkout's publication_read_only project setting. Git remotes are unchanged. "
        "Re-run setup and choose a writable source, Fork or Duplicate. "
        "For a saved run, pass `--publication-destination source` with "
        "`yoke setup --resume <run-id>` after confirming source write access. "
        "GitHub App connection and Git push permission are separate."
    )


def prevent_push(root: Path, remote: str = "origin", *, config_path=None) -> None:
    from yoke_cli.config import writer_projects

    writer_projects.set_publication_read_only(root, True, path=config_path)
    migrate_legacy(root, config_path=config_path)


def allow_source_push(root: Path, *, config_path=None) -> None:
    from yoke_cli.config import writer_projects

    migrate_legacy(root, config_path=config_path)
    writer_projects.set_publication_read_only(root, False, path=config_path)


def require_published_source(root: Path, selected_url: str, web_url: str) -> None:
    """Refuse to copy unverified local commits to a newly selected destination."""
    from yoke_cli.config.project_clone_resume import origin_is
    from yoke_cli.config.project_git_transport import git_current_branch
    from yoke_cli.config.project_onboard_support import ProjectOnboardError
    from yoke_cli.project_install import publication_reconcile as reconcile

    if origin_is(root, selected_url, web_url=web_url):
        return  # The existing owned-repository verifier owns a resumed push.
    source = reconcile.read_remote_state(
        root,
        branch=git_current_branch(root),
        remote="origin",
    )
    if source.status not in (reconcile.CURRENT, reconcile.BEHIND):
        raise ProjectOnboardError(
            "publication_source_unverified: Duplicate cannot silently publish "
            "local commits absent from the source, or an unreadable source. "
            "Reconcile those commits explicitly and restore source fetch "
            "access, then retry Duplicate. " + source.detail
        )
