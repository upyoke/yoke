"""Hand a newborn universe's one-time admin token to its operator.

Birth mints exactly one raw credential and the database keeps only its
hash, so this is the single moment the token exists. Where it goes decides
whether the banner's promise is true: a Compose bundle hands the server an
open descriptor onto an owner-only host file before dropping privileges,
and the token goes there while the log carries only the path. A server
started outside a bundle has no descriptor, so stdout stays the delivery
and the banner says so plainly instead of claiming secrecy it cannot keep.
"""

from __future__ import annotations

import os
from typing import Mapping

from yoke_contracts.self_host_bootstrap_output import (
    API_PUBLISH_ENV,
    FIRST_BOOT_TOKEN_FD_ENV,
    FIRST_BOOT_TOKEN_FILE_ENV,
    FIRST_BOOT_TOKEN_HOST_PATH_ENV,
    connect_url_from_publish_spec,
    first_boot_admin_token_block,
    first_boot_admin_token_notice,
)


class FirstBootTokenDeliveryError(RuntimeError):
    """The one-time admin token has nowhere safe to land; boot must stop."""


def deliver_first_boot_admin_token(
    raw_token: str,
    *,
    env: Mapping[str, str] | None = None,
    write=os.write,
) -> str:
    """Deliver the token and return the banner that was printed.

    Fails the boot when a bundle declared a token file the bootstrap did
    not open, rather than silently falling back to printing the credential
    into the very log the file exists to keep it out of.
    """
    environment = os.environ if env is None else env
    connect_url = connect_url_from_publish_spec(environment.get(API_PUBLISH_ENV, ""))
    descriptor = _declared_descriptor(environment)
    if descriptor is None:
        banner = first_boot_admin_token_block(raw_token, connect_url=connect_url)
        print(banner, flush=True)
        return banner
    host_path = (
        environment.get(FIRST_BOOT_TOKEN_HOST_PATH_ENV, "").strip()
        or environment.get(FIRST_BOOT_TOKEN_FILE_ENV, "").strip()
    )
    try:
        os.ftruncate(descriptor, 0)
        write(descriptor, (raw_token + "\n").encode("utf-8"))
        os.fsync(descriptor)
    except OSError as exc:
        raise FirstBootTokenDeliveryError(
            "the first-boot admin token file could not be written "
            f"({exc}); repair the bundle with `yoke self-host init --dir "
            "<bundle> --protect-existing`, then `docker compose up -d`"
        ) from exc
    banner = first_boot_admin_token_notice(
        host_path=host_path, connect_url=connect_url,
    )
    print(banner, flush=True)
    return banner


def _declared_descriptor(env: Mapping[str, str]) -> int | None:
    declared_file = env.get(FIRST_BOOT_TOKEN_FILE_ENV, "").strip()
    raw_descriptor = env.get(FIRST_BOOT_TOKEN_FD_ENV, "").strip()
    if not declared_file and not raw_descriptor:
        return None
    try:
        descriptor = int(raw_descriptor)
    except ValueError:
        descriptor = -1
    if descriptor < 0:
        raise FirstBootTokenDeliveryError(
            f"{FIRST_BOOT_TOKEN_FILE_ENV} names {declared_file or '<unset>'} but "
            f"{FIRST_BOOT_TOKEN_FD_ENV} carries no open descriptor: the server "
            "was started without its self-host bootstrap. Start it with "
            "`docker compose up -d` from the bundle directory"
        )
    return descriptor


__all__ = [
    "FirstBootTokenDeliveryError",
    "deliver_first_boot_admin_token",
]
