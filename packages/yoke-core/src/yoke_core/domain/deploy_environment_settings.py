"""Deployment-environment resolution for Yoke core-service deploys.

Resolves one project environment (``environments`` row by name within the
project's site) plus the project capabilities a core-container deploy needs
(``ssh``, ``aws-admin``, ``container-registry``, ``webapp-runtime``,
``health-endpoint``, ``pulumi-state``) into a single typed snapshot.

Authority model: the DB owns every value here (sites/environments settings +
project capabilities). Nothing is read from repo files, machine config, or
ambient cwd. Missing values fail loudly with the sanctioned write surface
named in the error (``python3 -m yoke_core.domain.projects
capability-merge-settings ...``) so an operator can repair authority instead
of patching code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    _first_mapping,
    load_project_renderer_settings,
)


class DeployEnvironmentError(ValueError):
    """A deploy environment could not be resolved from DB authority."""


_CAPABILITY_HINT = (
    "set it via: python3 -m yoke_core.domain.projects "
    "capability-merge-settings {project} {capability} --set <key>=<value> "
    "(absent rows are created; full-document writes go through "
    "capability-set-settings --base/--new)"
)


@dataclass(frozen=True)
class DeployEnvironment:
    """Typed snapshot of one deployable project environment."""

    project: str
    # Stable namespace every AWS resource for this deploy is named under;
    # defaults to ``project`` unless the site overrides it (see
    # project_renderer_settings.ProjectRendererSettings.deploy_namespace).
    deploy_namespace: str
    env_name: str
    site_id: str
    api_host: str
    origin_host: str
    origin_port: int
    ssh_user: str
    ssh_key_path: str
    aws_region: str
    aws_account_id: str
    repository_name: str
    api_port: int
    health_path: str
    stack_name: str
    activation_state: str
    state_backend: str
    database_name: str
    otel_exporter_endpoint: str = ""
    # Long-lived branch this env runs the HEAD of (environments.settings
    # .git.branch: main<->prod, stage<->stage). Empty = no declared branch;
    # the env takes worktree/SHA deploys (the ephemeral tier).
    git_branch: str = ""

    @property
    def registry_host(self) -> str:
        return f"{self.aws_account_id}.dkr.ecr.{self.aws_region}.amazonaws.com"

    def image_ref(self, tag: str) -> str:
        return f"{self.registry_host}/{self.repository_name}:{tag}"

    @property
    def api_health_url(self) -> str:
        return f"https://{self.api_host}{self.health_path}"

    @property
    def origin_health_url(self) -> str:
        port = "" if self.origin_port == 80 else f":{self.origin_port}"
        return f"http://{self.origin_host}{port}{self.health_path}"

    @property
    def compose_dir(self) -> str:
        return f"/opt/{self.deploy_namespace}-core"

    @property
    def log_group(self) -> str:
        return f"/{self.deploy_namespace}/{self.env_name}/core"

    @property
    def ssh_target(self) -> str:
        return f"{self.ssh_user}@{self.origin_host}"


def _require(value: Any, *, what: str, hint: str) -> Any:
    if value in (None, "", [], {}):
        raise DeployEnvironmentError(f"{what} is not configured; {hint}")
    return value


def _capability(
    settings: ProjectRendererSettings, capability: str
) -> Dict[str, Any]:
    found = settings.capabilities.get(capability)
    if not isinstance(found, dict) or not found:
        raise DeployEnvironmentError(
            f"project '{settings.project}' is missing the '{capability}' "
            "capability; "
            + _CAPABILITY_HINT.format(
                project=settings.project, capability=capability
            )
        )
    return found


def _capability_value(
    settings: ProjectRendererSettings, capability: str, key: str
) -> Any:
    return _require(
        _capability(settings, capability).get(key),
        what=f"'{capability}' capability key '{key}' for project "
        f"'{settings.project}'",
        hint=_CAPABILITY_HINT.format(
            project=settings.project, capability=capability
        ),
    )


def _env_mapping(env_settings: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = env_settings.get(key)
    return value if isinstance(value, dict) else {}


def resolve_deploy_environment(project: str, env_name: str) -> DeployEnvironment:
    """Resolve *env_name* for *project* from DB authority, loudly.

    ``project`` accepts a slug or numeric id (delegated to the renderer
    settings loader). ``env_name`` matches ``environments.name`` (for
    example ``prod`` or ``stage``).
    """
    return deploy_environment_from_settings(
        load_project_renderer_settings(project), env_name
    )


def deploy_environment_from_settings(
    settings: ProjectRendererSettings, env_name: str
) -> DeployEnvironment:
    """Pure projection of a settings snapshot onto one deploy environment."""
    env = next(
        (e for e in settings.environments if e.name == env_name), None
    )
    if env is None:
        available = ", ".join(e.name for e in settings.environments) or "none"
        raise DeployEnvironmentError(
            f"project '{settings.project}' has no environment named "
            f"'{env_name}' (available: {available}); add the environments "
            "row with structured settings before deploying"
        )

    env_hint = (
        f"add it to environments.settings for environment '{env_name}' of "
        f"project '{settings.project}'"
    )
    hosts = _env_mapping(env.settings, "hosts")
    pulumi = _env_mapping(env.settings, "pulumi")
    database = _env_mapping(env.settings, "database")
    observability = _env_mapping(env.settings, "observability")
    git = _env_mapping(env.settings, "git")

    ssh = _capability(settings, "ssh")
    ssh_user = ssh.get("user") or ssh.get("default_user") or ""
    # Per-env private-key override: servers[0].ssh_key_path on the
    # environment row wins over the project-level ssh capability so a
    # strictly isolated env (e.g. stage with its own key pair) never
    # falls back to another env's pem. The capability stays the loud
    # fallback and is only consulted when no override exists.
    server = _first_mapping(env.settings.get("servers"))
    ssh_key_override = server.get("ssh_key_path")
    if isinstance(ssh_key_override, str) and ssh_key_override:
        ssh_key_path = ssh_key_override
    else:
        ssh_key_path = str(_capability_value(settings, "ssh", "key_path"))
    aws_region = _capability_value(settings, "aws-admin", "region")
    state_bucket = _capability_value(settings, "pulumi-state", "state_bucket")

    return DeployEnvironment(
        project=settings.project,
        deploy_namespace=settings.deploy_namespace,
        env_name=env_name,
        site_id=settings.site_id,
        api_host=str(_require(hosts.get("api"), what="hosts.api", hint=env_hint)),
        origin_host=str(
            _require(hosts.get("origin"), what="hosts.origin", hint=env_hint)
        ),
        origin_port=int(hosts.get("origin_port") or 80),
        ssh_user=str(
            _require(
                ssh_user,
                what=f"'ssh' capability user for project '{settings.project}'",
                hint=_CAPABILITY_HINT.format(
                    project=settings.project, capability="ssh"
                ),
            )
        ),
        ssh_key_path=ssh_key_path,
        aws_region=str(aws_region),
        aws_account_id=str(
            _capability_value(settings, "aws-admin", "account_id")
        ),
        repository_name=str(
            _capability_value(settings, "container-registry", "repository")
        ),
        api_port=int(_capability_value(settings, "webapp-runtime", "api_port")),
        health_path=str(
            _capability_value(settings, "health-endpoint", "health_path")
        ),
        stack_name=str(
            _require(
                pulumi.get("stack_name"), what="pulumi.stack_name", hint=env_hint
            )
        ),
        activation_state=str(pulumi.get("activation_state") or "active"),
        state_backend=f"s3://{state_bucket}?region={aws_region}",
        database_name=str(
            _require(database.get("name"), what="database.name", hint=env_hint)
        ),
        otel_exporter_endpoint=str(
            observability.get("otel_exporter_endpoint") or ""
        ),
        git_branch=str(git.get("branch") or ""),
    )


def declared_env_branch(project: str, env_name: str) -> str:
    """Return *env_name*'s declared deploy branch for *project*, or ``""``.

    Narrow read of ``environments.settings.git.branch`` that tolerates env
    rows that are not deploy-capable (no hosts/pulumi/database settings) and
    a missing env row entirely — the deployment-pipeline merged gate consumes
    this for any flow ``target_env``, including envs that exist only as
    topology declarations. DB/load failures propagate loudly; they must not
    silently read as "no declared branch".
    """
    settings = load_project_renderer_settings(project)
    env = next(
        (e for e in settings.environments if e.name == env_name), None
    )
    if env is None:
        return ""
    git = _env_mapping(env.settings, "git")
    branch = git.get("branch")
    return branch if isinstance(branch, str) else ""


def auto_deploy_envs_for_branch(project: str, branch: str) -> List[str]:
    """Return env names of *project* that auto-deploy on a push to *branch*.

    An environment qualifies when its ``environments.settings`` BOTH
    declare ``git.branch == branch`` AND ``deploy.auto_on_push == true``
    (strict JSON boolean; absent or any other value = false). Per-env
    policy is DB truth — the operator flips it with
    ``python3 -m yoke_core.domain.projects environment-merge-settings
    <env-id> --set deploy.auto_on_push=true``. An empty *branch* never
    matches: envs with no declared branch are the ephemeral tier, not
    push targets.
    """
    if not branch:
        return []
    return auto_deploy_envs_from_settings(
        load_project_renderer_settings(project), branch
    )


def auto_deploy_envs_from_settings(
    settings: ProjectRendererSettings, branch: str
) -> List[str]:
    """Pure projection of the per-env auto-deploy-on-push policy."""
    matched: List[str] = []
    if not branch:
        return matched
    for env in settings.environments:
        git = _env_mapping(env.settings, "git")
        deploy = _env_mapping(env.settings, "deploy")
        if git.get("branch") == branch and deploy.get("auto_on_push") is True:
            matched.append(env.name)
    return matched
