"""Git-owned publication policy shared by setup, publication and work entry."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts import terminal_detached_process

READ_ONLY_PUSH_URL = "disabled://yoke-read-only"


def push_urls(root: str | Path, remote: str = "origin") -> tuple[str, ...]:
    result = terminal_detached_process.run(
        ["git", "-C", str(root), "remote", "get-url", "--push", "--all", remote],
        capture_output=True, text=True, timeout=30,
    )
    return tuple(result.stdout.splitlines()) if result.returncode == 0 else ()


def read_only(root: str | Path, remote: str = "origin") -> bool:
    return READ_ONLY_PUSH_URL in push_urls(root, remote)


def recovery(remote: str = "origin") -> str:
    return (
        f"publication_destination_read_only: {remote} permits fetching only. "
        "Re-run setup and choose a writable source, Fork or Duplicate, or "
        f"restore pushes to this exact source with `git remote set-url --push "
        f"{remote} <source-repository-url>` only after confirming source write access. "
        "Select a different repository through setup so its project binding agrees. "
        "GitHub App connection and Git push permission are separate."
    )


def prevent_push(root: Path, remote: str = "origin") -> None:
    from yoke_cli.config.project_git_transport import run_git

    run_git(root, "config", "--local", "--replace-all",
            f"remote.{remote}.pushurl", READ_ONLY_PUSH_URL)


def allow_source_push(root: Path) -> None:
    """Remove only the read-only selection, preserving any other push policy."""
    if read_only(root):
        from yoke_cli.config.project_git_transport import run_git

        run_git(root, "config", "--local", "--unset-all", "remote.origin.pushurl",
                "^disabled://yoke-read-only$")


def require_published_source(root: Path, selected_url: str, web_url: str) -> None:
    """Refuse to copy unverified local commits to a newly selected destination."""
    from yoke_cli.config.project_clone_resume import origin_is
    from yoke_cli.config.project_git_transport import git_current_branch
    from yoke_cli.config.project_onboard_support import ProjectOnboardError
    from yoke_cli.project_install import publication_reconcile as reconcile

    if origin_is(root, selected_url, web_url=web_url):
        return  # The existing owned-repository verifier owns a resumed push.
    source = reconcile.read_remote_state(
        root, branch=git_current_branch(root), remote="origin",
    )
    if source.status not in (reconcile.CURRENT, reconcile.BEHIND):
        raise ProjectOnboardError(
            "publication_source_unverified: Duplicate cannot silently publish "
            "local commits absent from the source, or an unreadable source. "
            "Reconcile those commits explicitly and restore source fetch "
            "access, then retry Duplicate. " + source.detail
        )
