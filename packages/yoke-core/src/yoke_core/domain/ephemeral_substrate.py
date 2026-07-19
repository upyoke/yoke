"""Canonical ephemeral-environment substrate: slug, ports, naming, policy.

Single Python owner of the deterministic conventions every ephemeral
surface shares — the branch slug, the hash-derived port, the compose
project name, the per-slug deploy directory, and the preview URL. The
nginx njs router and GitHub Actions prepare job installed by the
``ephemeral-environments`` Pack ship the same algorithm to runtimes where
Python is absent; this module is the source of truth they must match (locked
by golden-vector tests in ``test_ephemeral_substrate.py``).

Per-project policy lives in the ``ephemeral-env`` project capability:
which project and environment own the preview host (``host_project`` and
``host_env``), the
wildcard preview domain (``preview_domain``), how deploys are triggered
(``trigger``: ``"flow"`` for a core-service executor or ``"github-push"``
for a GitHub-Actions instantiation), the project-owned deployment flow used by
the flow trigger (``flow_id``), the port
ranges, and the teardown TTL.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
import re

#: ``deployment_flows.target_env`` value naming the worktree/preview tier.
#: Ephemeral flows deploy unmerged branches by design, so the deployment
#: pipeline's merged/CI gates do not apply to this tier.
EPHEMERAL_TARGET_ENV = "ephemeral"

_CAPABILITY = "ephemeral-env"
_CAPABILITY_HINT = (
    "set it via: yoke projects capability-settings merge --project {project} "
    "--cap-type ephemeral-env --set <key>=<value> (absent rows are created; "
    "full-document writes use capability-settings set --base/--new)"
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
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_FLOW_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


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
        raise EphemeralPolicyError(f"port_range must be positive, got {port_range}")
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8]
    return base_port + (int(digest, 16) % port_range)


def compose_project_name(preview_namespace: str, slug: str) -> str:
    """The Docker Compose project name for one preview slug."""
    return f"{preview_namespace}-{slug}"


def ephemeral_deploy_dir(preview_namespace: str, slug: str) -> str:
    """Per-slug deploy directory on the host box (home-relative)."""
    return f"~/{preview_namespace}/{slug}"


def preview_url(slug: str, preview_domain: str) -> str:
    """Public preview URL for one slug under the wildcard domain."""
    return f"https://{slug}.{preview_domain}"


@dataclass(frozen=True)
class EphemeralPolicy:
    """Typed snapshot of one project's ephemeral-env capability."""

    project: str
    # Project whose environment and provider capabilities host the preview.
    # Defaults to the source project, making ordinary projects self-hosting.
    host_project: str
    # Preview-only prefix for directories, Compose resources, routing, and
    # cleanup. It is deliberately distinct from the production namespace.
    preview_namespace: str
    trigger: str
    # Project-local deployment flow selected when trigger == "flow".
    flow_id: str
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

    *deploy_namespace* is the source project's stable resource namespace. A
    preview-only suffix is added unless the capability explicitly supplies
    ``preview_namespace``.
    """
    hint = _CAPABILITY_HINT.format(project=project)
    if not isinstance(cap, dict) or not cap:
        raise EphemeralPolicyError(
            f"project '{project}' has no '{_CAPABILITY}' capability settings; " + hint
        )
    trigger = str(cap.get("trigger") or "")
    if trigger not in _VALID_TRIGGERS:
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability has invalid "
            f"trigger {trigger!r} (expected one of {_VALID_TRIGGERS}); " + hint
        )
    flow_id = str(cap.get("flow_id") or "")
    if trigger == TRIGGER_FLOW and not flow_id:
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability declares "
            "trigger='flow' but no 'flow_id' naming its project-owned preview "
            "deployment flow; " + hint
        )
    if flow_id and not _FLOW_ID_RE.fullmatch(flow_id):
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability has unsafe "
            f"flow_id {flow_id!r}; use a lowercase hyphen-separated flow id; " + hint
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
    host_project = str(cap.get("host_project") or project)
    preview_namespace = str(
        cap.get("preview_namespace") or f"{deploy_namespace or project}-preview"
    )
    if not _NAMESPACE_RE.fullmatch(preview_namespace):
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability has unsafe "
            f"preview_namespace {preview_namespace!r}; use a lowercase "
            "hyphen-separated slug; " + hint
        )
    if not _NAMESPACE_RE.fullmatch(host_project):
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability has unsafe "
            f"host_project {host_project!r}; use a lowercase "
            "hyphen-separated project slug; " + hint
        )
    if not _DOMAIN_RE.fullmatch(preview_domain):
        raise EphemeralPolicyError(
            f"project '{project}' {_CAPABILITY} capability has invalid "
            f"preview_domain {preview_domain!r}; provide a DNS name without "
            "a wildcard prefix or URL scheme; " + hint
        )
    api_base_port = _positive_int(cap, "api_base_port", _DEFAULT_API_BASE_PORT)
    web_base_port = _positive_int(cap, "web_base_port", _DEFAULT_WEB_BASE_PORT)
    port_range = _positive_int(cap, "port_range", _DEFAULT_PORT_RANGE)
    ttl_hours = _positive_int(cap, "ttl_hours", _DEFAULT_TTL_HOURS)
    route_base_port = _positive_int(
        cap,
        "route_base_port",
        api_base_port if trigger == TRIGGER_FLOW else web_base_port,
    )
    for key, base in (
        ("api_base_port", api_base_port),
        ("web_base_port", web_base_port),
        ("route_base_port", route_base_port),
    ):
        if base + port_range - 1 > 65535:
            raise EphemeralPolicyError(
                f"project '{project}' {_CAPABILITY} capability {key} plus "
                "port_range exceeds TCP port 65535; " + hint
            )
    return EphemeralPolicy(
        project=project,
        host_project=host_project,
        preview_namespace=preview_namespace,
        trigger=trigger,
        flow_id=flow_id,
        preview_domain=preview_domain,
        host_env=host_env,
        api_base_port=api_base_port,
        web_base_port=web_base_port,
        port_range=port_range,
        ttl_hours=ttl_hours,
    )


def _positive_int(cap: dict, key: str, default: int) -> int:
    raw = cap.get(key, default)
    if isinstance(raw, bool):
        raise EphemeralPolicyError(f"{key} must be a positive integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise EphemeralPolicyError(f"{key} must be a positive integer") from exc
    if value <= 0:
        raise EphemeralPolicyError(f"{key} must be a positive integer")
    return value


def load_ephemeral_policy(project: str) -> EphemeralPolicy:
    """Load *project*'s ephemeral policy from DB capability authority."""
    from yoke_core.domain.project_renderer_settings import (
        load_project_renderer_settings,
    )

    settings = load_project_renderer_settings(project)
    return ephemeral_policy_from_capability(
        settings.project,
        settings.capabilities.get(_CAPABILITY),
        deploy_namespace=settings.deploy_namespace,
    )
