"""Canonical runtime-identity packet for status CLI and universe UI hosts.

One small structured packet is the source of truth for ``yoke status`` and
for every host that mounts the universe app. Resolvers already owned by
``engine_version`` and ``install_binding`` feed it — this module does not
invent a second version authority.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from yoke_contracts.engine_version import (
    ENGINE_DISTRIBUTION_NAME,
    local_handshake_version,
)
from yoke_contracts.install_binding import (
    KIND_PACKAGED_WHEEL,
    KIND_SOURCE_CHECKOUT,
    distribution_version_for_module,
    source_checkout_root,
)

PORTABILITY_LOCAL = "local"
PORTABILITY_SELFHOST = "selfhost"
PORTABILITY_HOSTED = "hosted"

INSTALL_KIND_HOSTED_PIN = "hosted_pin"

#: Honest display label when dist metadata and build identity are absent.
SOURCE_VERSION_LABEL = "source"

_DEFAULT_ENVIRONMENT_LABELS = {
    PORTABILITY_LOCAL: "local universe",
    PORTABILITY_SELFHOST: "self-hosted universe",
    PORTABILITY_HOSTED: "hosted universe",
}


def build_runtime_identity(
    *,
    portability_mode: str = PORTABILITY_LOCAL,
    environment_label: Optional[str] = None,
    install: Optional[Mapping[str, Any]] = None,
    version: Optional[str] = None,
    build: Optional[str] = None,
    module_file: Union[str, Path, None] = None,
) -> dict[str, Any]:
    """Return the compact packet describing the running product setup."""
    install_info = (
        dict(install) if install is not None else detect_install(module_file)
    )
    resolved_version = version
    if resolved_version is None:
        # Prefer install metadata, then the client distribution (never probe
        # yoke_core — product-boundary HTTPS clients are core-free).
        resolved_version = (
            str(install_info.get("version") or "")
            or local_handshake_version()
            or SOURCE_VERSION_LABEL
        )
    if not resolved_version:
        resolved_version = SOURCE_VERSION_LABEL
    resolved_build = (
        build if build is not None else os.environ.get("YOKE_BUILD_SHA", "")
    )
    mode = portability_mode or PORTABILITY_LOCAL
    return {
        "version": str(resolved_version),
        "install_kind": str(install_info.get("kind") or KIND_PACKAGED_WHEEL),
        "build": str(resolved_build or ""),
        "environment_label": (
            environment_label
            or _DEFAULT_ENVIRONMENT_LABELS.get(mode, "local universe")
        ),
        "portability_mode": mode,
    }


def detect_install(
    module_file: Union[str, Path, None] = None,
) -> dict[str, Any]:
    """Install binding for a loaded module origin.

    Callers in core/CLI pass their own ``__file__``. This contracts module
    never imports ``yoke_core`` — client packages must stay core-free.
    """
    if module_file is None:
        return {
            "kind": KIND_PACKAGED_WHEEL,
            "checkout_root": None,
            "module_origin": "",
            "version": local_handshake_version(),
        }
    resolved = Path(module_file)
    checkout_root = source_checkout_root(resolved)
    return {
        "kind": (
            KIND_SOURCE_CHECKOUT if checkout_root else KIND_PACKAGED_WHEEL
        ),
        "checkout_root": str(checkout_root) if checkout_root else None,
        "module_origin": str(resolved),
        "version": distribution_version_for_module(
            ENGINE_DISTRIBUTION_NAME, resolved,
        ),
    }


def mount_fields(packet: Mapping[str, Any]) -> dict[str, Any]:
    """JS-facing mount options derived from a packet (camelCase keys)."""
    identity = {
        "version": str(packet.get("version") or SOURCE_VERSION_LABEL),
        "installKind": str(packet.get("install_kind") or KIND_PACKAGED_WHEEL),
        "environmentLabel": str(
            packet.get("environment_label")
            or _DEFAULT_ENVIRONMENT_LABELS[PORTABILITY_LOCAL]
        ),
        "portabilityMode": str(
            packet.get("portability_mode") or PORTABILITY_LOCAL
        ),
    }
    build = str(packet.get("build") or "")
    if build:
        identity["build"] = build
    return {
        "versionLabel": identity["version"],
        "environmentLabel": identity["environmentLabel"],
        "runtimeIdentity": identity,
    }


def with_runtime_identity(report: dict[str, Any]) -> dict[str, Any]:
    """Attach the canonical packet onto a status report that already has install."""
    install = report.get("install")
    if isinstance(install, Mapping):
        report["runtime_identity"] = build_runtime_identity(install=install)
    return report


def human_identity_line(report: Mapping[str, Any]) -> str:
    """One human-readable status line for the packet, or empty when absent."""
    identity = report.get("runtime_identity")
    if not isinstance(identity, Mapping):
        return ""
    build = identity.get("build") or "-"
    return (
        "  identity: "
        f"version={identity.get('version') or '<missing>'} "
        f"kind={identity.get('install_kind') or '<missing>'} "
        f"build={build} "
        f"mode={identity.get('portability_mode') or '<missing>'}"
    )

__all__ = [
    "INSTALL_KIND_HOSTED_PIN",
    "PORTABILITY_HOSTED",
    "PORTABILITY_LOCAL",
    "PORTABILITY_SELFHOST",
    "SOURCE_VERSION_LABEL",
    "build_runtime_identity",
    "detect_install",
    "human_identity_line",
    "mount_fields",
    "with_runtime_identity",
]
