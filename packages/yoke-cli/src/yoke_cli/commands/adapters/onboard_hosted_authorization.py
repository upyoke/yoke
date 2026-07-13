"""Fresh hosted-onboarding authorization boundary."""

from __future__ import annotations

import argparse

from yoke_cli.config import onboard_destinations


def add_token_arguments(parser: argparse.ArgumentParser) -> None:
    """Register token inputs that apply only to explicit team servers."""
    parser.add_argument(
        "token",
        nargs="?",
        help="team-server API token; Yoke Cloud uses browser approval",
    )
    parser.add_argument(
        "--token-file",
        dest="token_file",
        default=None,
        help="team-server API token file; Yoke Cloud uses browser approval",
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


def usage_error(
    destination: str | None,
    explicit_token_source: bool,
    resuming: bool,
    should_prompt: bool,
) -> str | None:
    """Reject fresh Cloud paths that cannot complete browser approval."""
    if destination != onboard_destinations.DESTINATION_HOSTED:
        return None
    if explicit_token_source:
        return (
            "Yoke Cloud uses browser approval; remove TOKEN, --token-file, or "
            "--token-stdin and run onboarding interactively"
        )
    if not resuming and not should_prompt:
        return (
            "Yoke Cloud onboarding requires browser approval; run `yoke onboard "
            "--connect https://app.upyoke.com` interactively"
        )
    return None


__all__ = ["add_token_arguments", "has_explicit_token_source", "usage_error"]
