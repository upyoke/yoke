"""Return a newborn universe's token over its private host handoff."""

from __future__ import annotations

import os
import socket
from typing import Mapping

from yoke_contracts.self_host_handoff import HANDOFF_ACK, HANDOFF_TIMEOUT_SECONDS
from yoke_contracts.self_host_bootstrap_output import (
    API_PUBLISH_ENV,
    FIRST_BOOT_TOKEN_FD_ENV,
    FIRST_BOOT_TOKEN_HOST_PATH_ENV,
    connect_url_from_publish_spec,
    first_boot_admin_token_block,
    first_boot_admin_token_notice,
)


class FirstBootTokenDeliveryError(RuntimeError):
    """The one-time token has nowhere safe to land; its transaction must roll back."""


def deliver_first_boot_admin_token(
    raw_token: str, *, env: Mapping[str, str] | None = None
) -> str:
    """Wait for durable host storage before returning to the birth transaction."""
    environment = os.environ if env is None else env
    connect_url = connect_url_from_publish_spec(environment.get(API_PUBLISH_ENV, ""))
    host_path = environment.get(FIRST_BOOT_TOKEN_HOST_PATH_ENV, "").strip()
    raw_descriptor = environment.get(FIRST_BOOT_TOKEN_FD_ENV, "").strip()
    if not host_path and not raw_descriptor:
        banner = first_boot_admin_token_block(raw_token, connect_url=connect_url)
        print(banner, flush=True)
        return banner
    try:
        descriptor = int(raw_descriptor)
        if descriptor < 0:
            raise ValueError("negative descriptor")
    except ValueError:
        raise FirstBootTokenDeliveryError(
            "self_host_token_handoff_missing: bootstrap supplied no private descriptor; "
            "start with `yoke self-host init --protect-existing --start`"
        ) from None
    try:
        with socket.socket(fileno=os.dup(descriptor)) as handoff:
            handoff.sendall((raw_token + "\n").encode())
            handoff.settimeout(HANDOFF_TIMEOUT_SECONDS)
            acknowledged = bytearray()
            while len(acknowledged) < len(HANDOFF_ACK):
                chunk = handoff.recv(len(HANDOFF_ACK) - len(acknowledged))
                if not chunk:
                    break
                acknowledged.extend(chunk)
            if acknowledged != HANDOFF_ACK:
                raise OSError("host did not acknowledge durable token storage")
    except OSError:
        raise FirstBootTokenDeliveryError(
            "self_host_token_handoff_failed: host did not confirm token storage; "
            "repair the bundle's owner-only secrets directory, then retry "
            "`yoke self-host init --protect-existing --start`"
        ) from None
    banner = first_boot_admin_token_notice(host_path=host_path, connect_url=connect_url)
    print(banner, flush=True)
    return banner


__all__ = ["FirstBootTokenDeliveryError", "deliver_first_boot_admin_token"]
