"""Function ids scoped ``CLIENT_LOCAL`` — machine possession is the gate.

Split from :mod:`yoke_core.domain.function_authz_scope` so that module
stays inside the authored-file line budget. These operate on the
caller's own machine — its ``~/.yoke`` config or its checkout — so they
are never resolved server-side and carry no project/org permission.
"""

from __future__ import annotations

from yoke_core.domain.function_authz_types import AuthzSpec, CLIENT_LOCAL

CLIENT_LOCAL_BY_ID: dict[str, AuthzSpec] = {
    # Machine-local config / repo writes — gated by machine possession.
    "auth.set.run": AuthzSpec(CLIENT_LOCAL, None),
    "connection.set.run": AuthzSpec(CLIENT_LOCAL, None),
    "connection.remove.run": AuthzSpec(CLIENT_LOCAL, None),
    "env.use.run": AuthzSpec(CLIENT_LOCAL, None),
    "env.list.run": AuthzSpec(CLIENT_LOCAL, None),
    "config.example.run": AuthzSpec(CLIENT_LOCAL, None),
    "config.stamp_project_env.run": AuthzSpec(CLIENT_LOCAL, None),
    "status.run": AuthzSpec(CLIENT_LOCAL, None),
    "project.register.run": AuthzSpec(CLIENT_LOCAL, None),
    "packs.get.run": AuthzSpec(CLIENT_LOCAL, None),
    "packs.relink.run": AuthzSpec(CLIENT_LOCAL, None),
    "packs.update.run": AuthzSpec(CLIENT_LOCAL, None),
    "scratch.dispatch_inputs": AuthzSpec(CLIENT_LOCAL, None),
    # Render-into-checkout helpers — local repo writes.
    "agents.render.run": AuthzSpec(CLIENT_LOCAL, None),
    "agents.render.check": AuthzSpec(CLIENT_LOCAL, None),
    "packets.render.run": AuthzSpec(CLIENT_LOCAL, None),
    "packets.check.run": AuthzSpec(CLIENT_LOCAL, None),
    # Reads the caller's own .yoke/lint-config; never server-resolved.
    "lint.config.show": AuthzSpec(CLIENT_LOCAL, None),
}

__all__ = ["CLIENT_LOCAL_BY_ID"]
