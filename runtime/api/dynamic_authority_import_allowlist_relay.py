"""Dynamic engine-import allowlist entries for the standing relay's release.

Split from :mod:`runtime.api.dynamic_authority_import_allowlist_cli` for the
authored-file line budget; both are read as one roster.
"""

from __future__ import annotations

RELAY_DYNAMIC_AUTHORITY_IMPORTS = {
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/session_control_relay_release.py",
        "yoke_core.tools.session_relay_release",
    ): (
        "client_local_machine_state",
        "inspect and enforce the environment-pinned release in relay-local state",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/session_control_relay_release.py",
        "yoke_core.tools.session_relay_release_install",
    ): (
        "client_local_machine_state",
        "atomically install the environment's served release for the standing relay",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/session_control_relay_release.py",
        "yoke_core.tools.session_relay_local_install",
    ): (
        "client_local_machine_state",
        "resolve the installed launcher a local-universe relay runs instead of a release",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/session_control_relay_release.py",
        "yoke_core.domain.control_plane_background_jobs",
    ): (
        "local_universe_dispatch",
        "host the control plane's background jobs in a local universe's relay, "
        "the long-lived process that serves it in place of an API server",
    ),
}

__all__ = ["RELAY_DYNAMIC_AUTHORITY_IMPORTS"]
