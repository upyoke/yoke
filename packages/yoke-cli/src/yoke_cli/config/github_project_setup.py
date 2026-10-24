"""Converge a checkout's GitHub origin and repo-local sign-in wiring."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from yoke_cli.config import github_git_credentials, github_repo_config
from yoke_cli.config import project_publication_destination as destination
from yoke_contracts import github_origin


class GitHubProjectSetupError(RuntimeError):
    """Checkout sign-in could not be safely converged."""


def converge(root: Path, *, config_path: str | Path | None) -> dict[str, Any]:
    """Use one verified Yoke helper and clean HTTPS origin for GitHub."""
    if not (root / ".git").exists():
        return {"configured": False, "reason": "git-checkout-absent"}
    try:
        github = github_git_credentials._machine_github_config(config_path)
        if not github:
            return {
                "configured": False,
                "reason": "machine-github-not-configured",
                "recovery": "Run yoke github connect, then rerun project install",
            }
        origins = github_repo_config.values(root, "remote.origin.url")
        if not origins:
            return {"configured": False, "reason": "github-origin-absent"}
        if len(origins) != 1:
            raise GitHubProjectSetupError(
                "github-origin-ambiguous: origin has multiple URLs; select one "
                "repository with git remote set-url origin URL, then rerun install"
            )
        web_url = str(github.get("web_url") or "https://github.com")
        origin = origins[0]
        if "://" not in origin and not origin.startswith("git@"):
            return {"configured": False, "reason": "origin-outside-configured-github"}
        try:
            repository = github_origin.normalize_github_repository(
                origin, web_url=web_url
            )
        except github_origin.GitHubApiOriginError as exc:
            host = (
                origin[4:].split(":", 1)[0]
                if origin.startswith("git@")
                else urlsplit(origin).hostname
            )
            if (
                str(host or "").casefold()
                == str(urlsplit(web_url).hostname or "").casefold()
            ):
                raise GitHubProjectSetupError(
                    "github-origin-invalid: origin is not a safe GitHub repository URL; "
                    "set a clean HTTPS origin with git remote set-url origin URL, "
                    "then rerun project install"
                ) from exc
            return {"configured": False, "reason": "origin-outside-configured-github"}
        endpoint = github_origin.validate_github_web_endpoint(web_url)
        https_url = endpoint.url(f"/{repository}.git")
        push_urls = github_repo_config.values(root, "remote.origin.pushurl")
        if any(
            github_origin.normalize_github_repository(url, web_url=web_url).casefold()
            != repository.casefold()
            for url in push_urls
            if url != destination.LEGACY_READ_ONLY_PUSH_URL
        ):
            raise GitHubProjectSetupError(
                "github-push-target-mismatch: origin pushes to another repository; "
                "inspect git remote get-url --push --all origin, then correct the "
                "push target and rerun install"
            )
        read_only = destination.migrate_legacy(root, config_path=config_path)
        push_urls = [url for url in push_urls if url != destination.LEGACY_READ_ONLY_PUSH_URL]
        helper = github_git_credentials.configure_repo_helper(
            root, config_path=config_path
        )
        if not helper.get("configured"):
            return {
                **helper,
                "recovery": "Run yoke github connect, then rerun project install",
            }
        changes = []
        if helper["changed"]:
            changes.append("credential-helper")
        if not read_only and origins != [https_url]:
            github_repo_config.replace_values(
                root,
                "remote.origin.url",
                expected=origins,
                replacement=[https_url],
            )
            changes.append("origin-url")
        if (
            push_urls
            and not read_only
            and push_urls != [https_url]
        ):
            github_repo_config.replace_values(
                root,
                "remote.origin.pushurl",
                expected=push_urls,
                replacement=[https_url],
            )
            changes.append("origin-push-url")
        return {
            **helper,
            "origin": https_url,
            "changes": changes,
            "changed": bool(changes),
        }
    except GitHubProjectSetupError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise GitHubProjectSetupError(
            f"github-checkout-sign-in-convergence-failed: {exc}; inspect this "
            "checkout's origin and credential helper, run yoke github connect, "
            "then rerun project install"
        ) from exc
