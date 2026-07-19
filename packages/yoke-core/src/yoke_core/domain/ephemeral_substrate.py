"""Canonical ephemeral-environment substrate: slug, ports, naming, policy.

Single Python owner of the deterministic conventions every ephemeral
surface shares — the branch slug, the hash-derived port, the compose
project name, the per-slug deploy directory, and the preview URL. The
nginx njs router and GitHub Actions prepare job installed by the
``ephemeral-environments`` Pack ship the same algorithm to runtimes where
Python is absent; this module is the source of truth they must match (locked
by golden-vector tests in ``test_ephemeral_substrate.py``).

Per-project policy lives in the ``ephemeral-env`` project capability:
which environment's origin box hosts the previews (``host_env``), the
wildcard preview domain (``preview_domain``), how deploys are triggered
(``trigger``: ``"flow"`` for a core-service executor or ``"github-push"``
for a GitHub-Actions instantiation), the port
ranges, and the teardown TTL.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

#: ``deployment_flows.target_env`` value naming the worktree/preview tier.
#: Ephemeral flows deploy unmerged branches by design, so the deployment
#: pipeline's merged/CI gates do not apply to this tier.
EPHEMERAL_TARGET_ENV = "ephemeral"

_CAPABILITY = "ephemeral-env"
_CAPABILITY_HINT = (
    "set it via: python3 -m yoke_core.domain.projects "
    "capability-merge-settings {project} ephemeral-env --set <key>=<value> "
    "(absent rows are created; full-document writes go through "
    "capability-set-settings --base/--new)"
)

#: Universal defaults matching the ephemeral-environments Pack fallbacks.
_DEFAULT_WEB_BASE_PORT = 4000
_DEFAULT_API_BASE_PORT = 9000
_DEFAULT_PORT_RANGE = 100
_DEFAULT_TTL_HOURS = 24

#: Sanctioned trigger models for ephemeral deploys.
TRIGGER_FLOW = "flow"
TRIGGER_GITHUB_PUSH = "github-push"
_VALID_TRIGGERS = (TRIGGER_FLOW, TRIGGER_GITHUB_PUSH)


class EphemeralPolicyError(ValueError):
    """The project's ephemeral-env capability is missing or malformed."""


def slugify_branch(branch: str) -> str:
    """Slugify a branch name: lowercase, non-alnum runs become one dash.

    Parity contract with the GitHub-Actions prepare job's shell slugify
    (lowercase, ``[^a-z0-9]`` runs -> ``-``, strip edge dashes).
    """
    out = []
    prev_dash = False
    for ch in branch.lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                out.append("-")
                prev_dash = True
    return "".join(out).strip("-")


def derive_port(slug: str, base_port: int, port_range: int) -> int:
    """``base + int(sha256(slug)[:8], 16) % range``.

    Parity contract with ``ephemeral_port.js`` (njs wildcard routing) and
    the GitHub-Actions prepare job's shell computation — all three must
    agree or the wildcard router proxies to the wrong container.
    """
    if port_range <= 0:
        raise EphemeralPolicyError(
            f"port_range must be positive, got {port_range}"
        )
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8]
    return base_port + (int(digest, 16) % port_range)


def compose_project_name(project: str, slug: str) -> str:
    """The Docker Compose project name for one preview slug."""
    return f"{project}-{slug}"


def ephemeral_deploy_dir(project: str, slug: str) -> str:
    """Per-slug deploy directory on the host box (home-relative)."""
    return f"~/{project}-ephemeral/{slug}"


def preview_url(slug: str, preview_domain: str) -> str:
    """Public preview URL for one slug under the wildcard domain."""
    return f"https://{slug}.{preview_domain}"


@dataclass(frozen=True)
class EphemeralPolicy:
    """Typed snapshot of one project's ephemeral-env capability."""

    project: str
    # Stable namespace every host-box preview resource is named under —
    # the per-slug compose project, deploy directory, wildcard nginx site,
    # and TTL cleanup cron. Defaults to ``project`` but derives from
    # ``sites.settings.deploy_namespace`` so a re-parent (the site moving to
    # a differently-named project) does not strand or collide those
    # resources, which cannot be renamed without destroy-and-recreate.
    deploy_namespace: str
    trigger: str
    preview_domain: str
    host_env: str
    api_base_port: int
    web_base_port: int
    port_range: int
    ttl_hours: int

    def api_port_for(self, slug: str) -> int:
        return derive_port(slug, self.api_base_port, self.port_range)

    def web_port_for(self, slug: str) -> int:
        return derive_port(slug, self.web_base_port, self.port_range)


def ephemeral_policy_from_capability(
    project: str, cap: object, deploy_namespace: str = ""
) -> EphemeralPolicy:
    """Build the typed policy from a raw capability settings mapping.

    *deploy_namespace* is the stable resource namespace previews are named
    under; it falls back to *project* when the caller does not supply the
    site-configured value (``load_ephemeral_policy`` passes it in).
    """
    hint = _CAPABILITY_HINT.format(project=project)
    if not isinstance(cap, dict) or not cap:
        raise EphemeralPolicyError(
            f"project '{project}' has no '{_CAPABILITY}' capability settings; "
            + hint
        )
    trigger = str(cap.get("trigger") or "")
    if trigger not in _VALID_TRIGGERS:
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability has invalid "
            f"trigger {trigger!r} (expected one of {_VALID_TRIGGERS}); " + hint
        )
    preview_domain = str(cap.get("preview_domain") or "")
    if not preview_domain:
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability is missing "
            "'preview_domain'; " + hint
        )
    host_env = str(cap.get("host_env") or "")
    if trigger == TRIGGER_FLOW and not host_env:
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability declares "
            "trigger='flow' but no 'host_env' naming the environment whose "
            "origin box hosts the previews; " + hint
        )
    return EphemeralPolicy(
        project=project,
        deploy_namespace=deploy_namespace or project,
        trigger=trigger,
        preview_domain=preview_domain,
        host_env=host_env,
        api_base_port=int(cap.get("api_base_port") or _DEFAULT_API_BASE_PORT),
        web_base_port=int(cap.get("web_base_port") or _DEFAULT_WEB_BASE_PORT),
        port_range=int(cap.get("port_range") or _DEFAULT_PORT_RANGE),
        ttl_hours=int(cap.get("ttl_hours") or _DEFAULT_TTL_HOURS),
    )


def load_ephemeral_policy(project: str) -> EphemeralPolicy:
    """Load *project*'s ephemeral policy from DB capability authority."""
    from yoke_core.domain.project_renderer_settings import (
        load_project_renderer_settings,
    )

    settings = load_project_renderer_settings(project)
    return ephemeral_policy_from_capability(
        settings.project, settings.capabilities.get(_CAPABILITY),
        deploy_namespace=settings.deploy_namespace,
    )
