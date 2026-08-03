"""Cursor project permission and network-sandbox regions Yoke manages.

Cursor gates agent-initiated work at two layers that stack independently
of the hook chain, so a project whose hooks load correctly can still
prompt on (or outright fail) every Yoke command:

* ``.cursor/cli.json`` — ``permissions.allow`` decides which commands run
  without an approval prompt. The schema is strict: an allow-less
  deny-only file aborts every run before the agent starts.
* ``.cursor/sandbox.json`` — ``networkPolicy`` decides which hosts a
  sandboxed command may reach. Without the control-plane origins on the
  allow list, a network-touching ``yoke`` call fails inside the sandbox
  and the agent has to request wider permission per invocation.

This module owns the content of both managed regions. Command
permissions are machine-independent constants. Network origins are not:
they name whichever control plane and GitHub endpoint this machine is
configured against, so they resolve from machine config at install time
rather than being baked into a server-built bundle. A self-hosted or
differently-tenanted installation therefore allows its own origins
instead of inheriting whichever ones happened to be authored here.

Escalation caveat, worth knowing before widening anything here: an
explicit full-network permission request counts as an escalation and
prompts even for hosts the network policy already allows. Once these
origins are on the allow list, the correct move is to retry inside the
sandbox rather than request the wider permission — requesting it causes
the very per-command prompting the allow list exists to remove.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

CURSOR_CLI_REL = ".cursor/cli.json"
CURSOR_SANDBOX_REL = ".cursor/sandbox.json"

# Command families Yoke's own flows execute. Cursor's entry grammar is
# ``Shell(<command pattern>)`` / ``Read(<glob>)`` / ``Write(<glob>)``.
# File-level policy stays with the hook chain, which sees every Read and
# Write regardless of what this list allows.
CURSOR_CLI_ALLOW: Tuple[str, ...] = (
    "Shell(yoke *)",
    "Shell(git *)",
    "Shell(gh *)",
    "Read(**)",
    "Write(**)",
)

# Everything not named by the resolved origins stays blocked. This is the
# tighter fallback posture; the recommended zero-prompt posture lives in
# Cursor's own settings and is documented in CURSOR.md.
NETWORK_POLICY_DEFAULT = "deny"

# Cursor validates both files against a versioned schema, so a file this
# pass creates from nothing carries the marker alongside its region.
CURSOR_CLI_SCHEMA_VERSION = 1

_HTTPS_TRANSPORT = "https"


@dataclass(frozen=True)
class CursorConfigRegion:
    """One managed region: a unioned list, optionally beside a seeded scalar.

    ``rel`` is the repo-relative Cursor config file. ``container`` is the
    top-level object holding the region, ``list_key`` the list Yoke unions
    its entries into, and ``default_key`` an optional sibling scalar that
    is seeded only when absent so an operator's own choice always wins.
    """

    rel: str
    container: str
    list_key: str
    default_key: Optional[str] = None
    schema_version: Optional[int] = None


CURSOR_CONFIG_REGIONS: Tuple[CursorConfigRegion, ...] = (
    CursorConfigRegion(
        rel=CURSOR_CLI_REL,
        container="permissions",
        list_key="allow",
        schema_version=CURSOR_CLI_SCHEMA_VERSION,
    ),
    CursorConfigRegion(
        rel=CURSOR_SANDBOX_REL,
        container="networkPolicy",
        list_key="allow",
        default_key="default",
    ),
)

CURSOR_CONFIG_REGION_BY_REL: Dict[str, CursorConfigRegion] = {
    region.rel: region for region in CURSOR_CONFIG_REGIONS
}

# Repo-relative Cursor config files a merge pass owns a region inside. A
# bundle that shipped one as a literal file entry would overwrite the
# operator's own entries, which is what the merge exists to prevent.
CURSOR_CONFIG_RELS: Tuple[str, ...] = tuple(
    region.rel for region in CURSOR_CONFIG_REGIONS
)

# Install-manifest key holding the per-file records of what the merge added.
CURSOR_PERMISSIONS_MANIFEST_KEY = "cursor_permissions"


def _host(url: Any) -> Optional[str]:
    """Hostname of an absolute URL, or ``None`` when it names no host."""
    if not isinstance(url, str) or not url.strip():
        return None
    return urlsplit(url.strip()).hostname or None


def _load_machine_config() -> Mapping[str, Any]:
    """Machine config, or an empty mapping when it is absent/unreadable.

    An unreadable config degrades the network allow list to empty rather
    than failing the install; the doctor check reports the resulting gap.
    """
    from yoke_contracts.machine_config import runtime as machine_runtime

    try:
        return machine_runtime.load_config() or {}
    except (OSError, ValueError):
        return {}


def control_plane_origins(
    config: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Hosts a sandboxed Yoke command legitimately reaches on this machine.

    The set is exactly the configured https control-plane endpoints plus
    the configured GitHub API and web endpoints — the hosts Yoke's own
    flows contact. Nothing is inferred from a vendor default.
    """
    if config is None:
        config = _load_machine_config()
    origins: set[str] = set()
    connections = config.get("connections")
    if isinstance(connections, Mapping):
        for entry in connections.values():
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("transport") or "") != _HTTPS_TRANSPORT:
                continue
            host = _host(entry.get("api_url"))
            if host:
                origins.add(host)
    github = config.get("github")
    if isinstance(github, Mapping):
        for key in ("api_url", "web_url"):
            host = _host(github.get(key))
            if host:
                origins.add(host)
    return sorted(origins)


def managed_cursor_regions(
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Managed region values keyed by repo-relative Cursor config path.

    Each value carries the entries to union under the region's list key
    and, where the region declares one, the scalar to seed when absent.
    """
    return {
        CURSOR_CLI_REL: {"entries": list(CURSOR_CLI_ALLOW)},
        CURSOR_SANDBOX_REL: {
            "entries": control_plane_origins(config),
            "default": NETWORK_POLICY_DEFAULT,
        },
    }


__all__ = [
    "CURSOR_CLI_ALLOW",
    "CURSOR_CLI_REL",
    "CURSOR_CLI_SCHEMA_VERSION",
    "CURSOR_CONFIG_REGIONS",
    "CURSOR_CONFIG_REGION_BY_REL",
    "CURSOR_CONFIG_RELS",
    "CURSOR_PERMISSIONS_MANIFEST_KEY",
    "CURSOR_SANDBOX_REL",
    "CursorConfigRegion",
    "NETWORK_POLICY_DEFAULT",
    "control_plane_origins",
    "managed_cursor_regions",
]
