"""Fresh hosted-onboarding authorization boundary."""

from __future__ import annotations

import argparse
from pathlib import Path

from yoke_cli.config import onboard_destinations, machine_config
from yoke_cli.config.install_advice import hosted_connect_url


def add_token_arguments(parser: argparse.ArgumentParser) -> None:
    """Register token inputs that apply only to explicit team servers."""
    parser.add_argument(
        "token",
        nargs="?",
        help="team-server API token; configured company sign-in and Cloud use browser approval",
    )
    parser.add_argument(
        "--token-file",
        dest="token_file",
        default=None,
        help="team-server API token file; configured company sign-in and Cloud use browser approval",
    )
    parser.add_argument(
        "--token-stdin",
        dest="token_stdin",
        action="store_true",
        help="read a team-server API token from stdin",
    )


def has_explicit_token_source(parsed: argparse.Namespace) -> bool:
    """Whether this invocation supplied a manual token source."""
    return bool(parsed.token or parsed.token_file or parsed.token_stdin)


def hydrate_saved(parsed: argparse.Namespace, destination: str | None) -> bool:
    """Reuse the same stored browser-approved reference as the TUI."""
    if (
        destination != onboard_destinations.DESTINATION_HOSTED
        or has_explicit_token_source(parsed)
    ):
        return False
    try:
        connection = machine_config.active_connection(
            parsed.config_path, explicit_env=parsed.env_name
        )
    except (OSError, RuntimeError, ValueError):
        return False
    source = connection.get("credential_source") or {}
    api_url = str(connection.get("api_url") or "")
    if (
        connection.get("transport") != "https"
        or source.get("kind") != "token_file"
        or not onboard_destinations.matches_stored_hosted_authority(
            parsed.api_url, api_url
        )
    ):
        return False
    token_file = Path(str(source.get("path") or "")).expanduser()
    if not token_file.is_file():
        return False
    parsed.api_url, parsed.token_file = api_url, str(token_file)
    parsed.env_name = str(connection.get("env") or parsed.env_name or "")
    return True


def usage_error(
    destination: str | None,
    explicit_token_source: bool,
    resuming: bool,
    should_prompt: bool,
    *,
    api_url: object = None,
    env_name: object = None,
) -> str | None:
    """Reject fresh Cloud paths that cannot complete browser approval."""
    if destination != onboard_destinations.DESTINATION_HOSTED:
        return None
    connect_url = hosted_connect_url(api_url, env_name)
    if explicit_token_source:
        return (
            "Yoke Cloud uses browser approval; remove TOKEN, --token-file, or "
            "--token-stdin. From an agent, run `yoke setup --agent --connect "
            f"{connect_url}` and show the person its browser step."
        )
    if not resuming and not should_prompt:
        return (
            "browser_approval_required: Yoke Cloud onboarding requires browser approval; "
            f"from an agent, run `yoke setup --agent --connect {connect_url}` "
            "and show the person its browser step. In a terminal, run "
            f"`yoke setup --connect {connect_url}`."
        )
    return None


__all__ = ["add_token_arguments", "has_explicit_token_source", "usage_error"]
