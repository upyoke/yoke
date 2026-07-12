"""Safe helper reattachment for registered GitHub HTTPS checkouts."""

from __future__ import annotations

from pathlib import Path
import urllib.parse

from yoke_cli.config import github_git_credentials, github_repo_config, machine_config
from yoke_contracts import github_origin


def reattach(config_path: str | Path | None) -> dict[str, int]:
    """Remove old-origin Yoke chains, then attach only matching new origins."""
    counts = {"reattached": 0, "removed": 0, "skipped": 0, "failed": 0}
    try:
        github = machine_config.github_config(config_path)
        checkouts = machine_config.all_registered_checkouts(
            config_path, existing_only=True,
        )
    except (OSError, machine_config.MachineConfigError):
        counts["failed"] += 1
        return counts
    web_url = str(github.get("web_url") or "")
    try:
        helper_key = github_git_credentials.credential_helper_key(web_url)
    except (OSError, github_origin.GitHubApiOriginError):
        counts["failed"] += len(checkouts) or 1
        return counts
    for root in checkouts:
        cleanup = github_git_credentials.remove_repo_helpers(
            root, config_path=config_path,
        )
        counts["removed"] += cleanup["removed"]
        if cleanup["failed"]:
            counts["failed"] += cleanup["failed"]
            continue
        remote_state = has_matching_https_remote(root, web_url=web_url)
        if remote_state is None:
            counts["failed"] += 1
            continue
        if remote_state is False:
            counts["skipped"] += 1
            continue
        values, read_failed = github_git_credentials._local_config_values(
            root, helper_key,
        )
        if read_failed or any(
            value and not github_git_credentials._is_yoke_helper(
                value, config_path=config_path,
            )
            for value in values
        ):
            counts["failed"] += 1
            continue
        try:
            result = github_git_credentials.configure_repo_helper(
                root, config_path=config_path,
            )
        except (OSError, RuntimeError):
            counts["failed"] += 1
            continue
        if result.get("configured") is True:
            counts["reattached"] += 1
        else:
            counts["failed"] += 1
    return counts


def has_matching_https_remote(root: Path, *, web_url: str) -> bool | None:
    try:
        urls = github_repo_config.matching_remote_urls(root)
    except (OSError, github_repo_config.GitHubRepoConfigError):
        return None
    endpoint = github_origin.validate_github_web_endpoint(web_url)
    unsafe_same_host = False
    for raw_url in urls:
        try:
            parsed = urllib.parse.urlsplit(raw_url)
        except ValueError:
            continue
        if parsed.scheme.casefold() != "https":
            continue
        if str(parsed.hostname or "").casefold() != str(
            urllib.parse.urlsplit(endpoint.base_url).hostname or ""
        ).casefold():
            continue
        try:
            github_origin.normalize_github_repository(
                raw_url, web_url=endpoint.base_url,
            )
        except github_origin.GitHubApiOriginError:
            unsafe_same_host = True
            continue
        return True
    return None if unsafe_same_host else False


__all__ = ["has_matching_https_remote", "reattach"]
