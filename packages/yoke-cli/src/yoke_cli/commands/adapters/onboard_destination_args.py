"""Deployment-destination flag surface for the ``yoke onboard`` adapter.

Owns the ``--local`` / ``--connect URL`` group and the resolution that
folds flags, the destination environment override, and a resumed run's
stored destination into one ``(destination, env_name)`` answer with any
usage error, so :mod:`onboard` (the adapter) stays a thin dispatcher.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from yoke_cli.config import onboard_destinations
from yoke_cli.config.local_universe_setup import LOCAL_ENV
from yoke_contracts.machine_config.schema import ENV_OVERRIDE


def add_destination_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--local",
        dest="destination_local",
        action="store_true",
        help=(
            "host this Yoke on this machine: create or verify the free "
            "local universe (no account, no token)"
        ),
    )
    group.add_argument(
        "--connect",
        dest="connect_url",
        default=None,
        metavar="URL",
        help="connect this machine to the Yoke server at URL",
    )


@dataclass(frozen=True)
class DestinationChoice:
    """Resolved destination answer, or the usage error that blocks it."""

    destination: str | None = None
    env_name: str = ""
    error: str | None = None


def resolve_destination(parsed: argparse.Namespace) -> DestinationChoice:
    """Fold flags, override, and resume into one destination + env answer.

    Mutates ``parsed.api_url`` when ``--connect URL`` supplies it. Returns
    an ``error`` (exit-code-2 message) for contradictory inputs.
    """
    try:
        destination, destination_api_url = onboard_destinations.resolve_choice(
            local_flag=parsed.destination_local,
            connect_url=parsed.connect_url,
            override_value=os.environ.get(onboard_destinations.DESTINATION_OVERRIDE),
            resumed=getattr(parsed, "destination", None),
        )
    except ValueError as exc:
        return DestinationChoice(error=str(exc))
    if destination_api_url:
        given_api_url = str(parsed.api_url or "").strip()
        if given_api_url and (
            given_api_url.rstrip("/") != destination_api_url.rstrip("/")
        ):
            return DestinationChoice(
                error="--connect URL and --api-url disagree; pass just one",
            )
        parsed.api_url = destination_api_url
    if destination is None and str(parsed.api_url or "").strip():
        destination = onboard_destinations.destination_for_api_url(parsed.api_url)
    if destination == onboard_destinations.DESTINATION_LOCAL:
        conflict = _local_destination_conflict(parsed)
        if conflict:
            return DestinationChoice(error=conflict)
        return DestinationChoice(destination=destination, env_name=LOCAL_ENV)
    env_name = parsed.env_name or os.environ.get(ENV_OVERRIDE, "").strip()
    if not env_name and destination is not None:
        env_name = onboard_destinations.DEFAULT_SIGN_IN_ENV
    return DestinationChoice(destination=destination, env_name=env_name)


def missing_required_flags(
    parsed: argparse.Namespace,
    *,
    env_name: str,
    local_destination: bool,
) -> list[str]:
    """Return connection flags still required by a nonlocal lane."""
    if local_destination:
        return []
    return [
        flag
        for flag, value in (("--env", env_name), ("--api-url", parsed.api_url))
        if not value
    ]


def token_sources(parsed: argparse.Namespace) -> list[bool]:
    """Truth values for the mutually exclusive token input surfaces."""
    return [bool(parsed.token), bool(parsed.token_file), bool(parsed.token_stdin)]


def _local_destination_conflict(parsed: argparse.Namespace) -> str | None:
    """Flags that contradict the local destination (which has no sign-in).

    ``yoke_cli.main`` folds a ``--env NAME`` anywhere on the command line
    into the :data:`ENV_OVERRIDE` environment override before the adapter
    runs, so the env conflict is read from both surfaces.
    """
    explicit_env = str(parsed.env_name or os.environ.get(ENV_OVERRIDE, "")).strip()
    if explicit_env and explicit_env != LOCAL_ENV:
        return (
            f"--local owns the {LOCAL_ENV!r} env label; drop --env "
            f"{explicit_env} (or unset {ENV_OVERRIDE})"
        )
    if str(parsed.api_url or "").strip():
        return "--local runs on this machine; --api-url does not apply"
    if parsed.token or parsed.token_file or parsed.token_stdin:
        return "--local needs no API token; the local universe uses a machine-local DSN"
    return None


__all__ = [
    "DestinationChoice",
    "add_destination_args",
    "missing_required_flags",
    "resolve_destination",
    "token_sources",
]
