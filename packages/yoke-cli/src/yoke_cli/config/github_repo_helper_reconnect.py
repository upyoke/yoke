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
            config_path,
            existing_only=True,
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
            root,
            config_path=config_path,
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
            root,
            helper_key,
        )
        if read_failed or any(
            value
            and not github_git_credentials._is_yoke_helper(
                value,
                config_path=config_path,
            )
            for value in values
        ):
            counts["failed"] += 1
            continue
        try:
            result = github_git_credentials.configure_repo_helper(
                root,
                config_path=config_path,
            )
        except (OSError, RuntimeError):
            counts["failed"] += 1
            continue
        if result.get("configured") is True:
            counts["reattached"] += 1
        else:
            counts["failed"] += 1
    return counts


def restore_missing_bundle(config_path: str | Path | None) -> dict[str, object]:
    """Rebuild the helper bundle a reinstall wiped from site-packages.

    Detection reads only registered checkouts' git config, matching each
    configured helper value against the *currently expected* helper path by
    shape (:func:`github_git_credentials._is_yoke_helper`) rather than by
    checking whether the underlying file exists — the file is exactly what a
    ``uv tool install --reinstall`` just deleted, while the git config that
    names it survives untouched. Absent any matching reference this is a
    legitimate no-op: it never installs a helper for a machine that never
    configured one, and it requires no GitHub App configuration to detect a
    reference already sitting in git config.

    A value can also *look* Yoke-shaped (the stable helper filename, the
    right argument count) without being verifiable: verification reads the
    prior helper file's content markers, and a reinstall that also changed
    the Python runtime path deletes that file along with the bundle, leaving
    nothing left to read. Reporting that as "unconfigured" would hide a real
    broken reference; reporting it as a silent success would risk rewriting
    an unrelated program's config over an unverified guess. It is reported
    as inconclusive (``configured: None``) instead, naming the checkout and
    key so an operator can inspect and reconnect deliberately. A git-config
    or machine-config read failure is reported the same way, distinct from
    a genuinely clean machine that never configured a helper at all.
    """
    try:
        checkouts = machine_config.all_registered_checkouts(
            config_path,
            existing_only=True,
        )
    except (OSError, machine_config.MachineConfigError) as exc:
        return {
            "configured": None,
            "repaired": False,
            "error": f"could not read machine config: {exc}",
        }
    # Classify every registered checkout before acting: a confirmed match
    # earlier in the list must not short-circuit past an unresolved
    # reference later in it, or that unresolved checkout is silently
    # dropped from a result that reads as clean.
    matched = False
    ambiguous: str | None = None
    unreadable: list[Path] = []
    for root in checkouts:
        outcome = _classify_helper_reference(root, config_path=config_path)
        if outcome == "match":
            matched = True
        elif outcome == "ambiguous" and ambiguous is None:
            ambiguous = str(root)
        elif outcome == "unreadable":
            unreadable.append(root)

    unresolved = _unresolved_reference_error(ambiguous, unreadable)
    if not matched:
        if unresolved is not None:
            return {"configured": None, "repaired": False, "error": unresolved}
        return {"configured": False, "repaired": False}

    try:
        github_git_credentials.install_stable_helper()
    except (OSError, github_git_credentials.GitHubCredentialBundleError) as exc:
        error = str(exc)
        if unresolved is not None:
            error = f"{error}; also unresolved: {unresolved}"
        return {"configured": True, "repaired": False, "error": error}
    if unresolved is not None:
        return {"configured": True, "repaired": True, "error": unresolved}
    return {"configured": True, "repaired": True}


def _unresolved_reference_error(
    ambiguous: str | None,
    unreadable: list[Path],
) -> str | None:
    if ambiguous is not None:
        return (
            f"{ambiguous} names a git credential helper that looks like "
            "Yoke's but its prior runtime path is gone, so it cannot be "
            "verified; reconnect GitHub (yoke github connect) or repair "
            "that checkout's git config manually"
        )
    if unreadable:
        names = ", ".join(str(path) for path in unreadable)
        return f"could not read git config for: {names}"
    return None


def _classify_helper_reference(
    root: Path,
    *,
    config_path: str | Path | None,
) -> str:
    """Return "match" / "ambiguous" / "unreadable" / "none" for *root*."""
    try:
        keys = github_repo_config.helper_keys(root)
    except github_repo_config.GitHubRepoConfigError:
        return "unreadable"
    saw_ambiguous = False
    for key in keys:
        try:
            values = github_repo_config.values(root, key)
        except github_repo_config.GitHubRepoConfigError:
            return "unreadable"
        for value in values:
            if not value:
                continue
            if github_git_credentials._is_yoke_helper(value, config_path=config_path):
                return "match"
            if github_git_credentials._looks_like_yoke_helper(value):
                saw_ambiguous = True
    return "ambiguous" if saw_ambiguous else "none"


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
        if (
            str(parsed.hostname or "").casefold()
            != str(urllib.parse.urlsplit(endpoint.base_url).hostname or "").casefold()
        ):
            continue
        try:
            github_origin.normalize_github_repository(
                raw_url,
                web_url=endpoint.base_url,
            )
        except github_origin.GitHubApiOriginError:
            unsafe_same_host = True
            continue
        return True
    return None if unsafe_same_host else False


__all__ = ["has_matching_https_remote", "reattach", "restore_missing_bundle"]
