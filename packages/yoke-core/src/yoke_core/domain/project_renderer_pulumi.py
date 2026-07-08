"""Pulumi rendering helpers for the project template renderer.

Owns legacy stack-set rendering (``stacks``) and additive environment stack
instances (``stackInstances``). Pulumi YAML and Python program files render
without ``_auto_header()`` so byte-equivalent source/render checks stay clean.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Dict, List

from .project_renderer_pulumi_context import (
    _pulumi_context_from_settings,
)
from . import json_helper
from .project_renderer_pulumi_instances import (
    gather_pulumi_stack_instances,
    instance_template_values,
)
from .project_renderer_pulumi_runner_fleet import runner_fleet_values
from .project_renderer_pulumi_state import (  # noqa: F401
    _operator_state_lines_from_settings,
    _parse_config_values,
    _preserve_operator_state_lines,
    _warn_on_config_divergence,
)
from .project_renderer_pulumi_stack_types import (
    STACK_TYPE_SPECS,
    gather_pulumi_stacks,
)
from .project_renderer_settings import (
    ProjectRendererSettings,
    _stringify,
    load_project_renderer_settings,
)
from .project_renderer_values import _values_from_settings


def gather_pulumi_values(
    project: str,
    project_root: Path,
    settings: ProjectRendererSettings | None = None,
) -> Dict[str, str]:
    """Return the Pulumi value dict: inherited keys + VPS + Pulumi + CI keys."""
    del project_root
    if settings is None:
        settings = load_project_renderer_settings(project)
    values = dict(_values_from_settings(project, settings))

    data = _pulumi_context_from_settings(settings)

    # Three newly-surfaced VPS keys (camelCase JSON -> snake_case output).
    values["vps_instance_type"] = _stringify(data.get("vpsInstanceType"))
    values["vps_root_volume_gb"] = _stringify(data.get("vpsRootVolumeGb"))
    values["vps_ssh_key_name"] = _stringify(data.get("vpsSshKeyName"))

    # CloudFront origin Id: required per project so the rendered stack YAML
    # carries the project's own origin Id (no template-level default). Empty
    # string passes through to the rendered YAML when the context omits it —
    # render-time validation belongs to the template caller, not the gatherer.
    values["origin_id"] = _stringify(data.get("originId"))
    values["distribution_bucket_name"] = _stringify(
        data.get("distributionBucketName")
    )
    values["domain_txt_records_json"] = _domain_txt_records_json(data)
    values["domain_mx_records_json"] = _domain_mx_records_json(data)

    # Pulumi-specific keys with computed defaults when fields are missing.
    # Named under the deploy namespace (defaults to the project slug), never
    # the live project slug — so a resource keeps its name when the site is
    # re-parented to a differently-named project.
    # ``deploy_namespace`` (the stack config naming input) is set in the base
    # values dict by _values_from_settings; here it just seeds the computed
    # stack-name / bucket / KMS defaults below.
    ns = settings.deploy_namespace
    values["kms_key_alias"] = _stringify(
        data.get("kmsKeyAlias"), f"alias/{ns}-pulumi-state"
    )
    values["state_bucket"] = _stringify(
        data.get("stateBucket"), f"{ns}-pulumi-state"
    )
    values["pulumi_infra_stack_name"] = _stringify(
        data.get("pulumiInfraStackName"), f"{ns}-infra"
    )
    values["pulumi_vps_stack_name"] = _stringify(
        data.get("pulumiVpsStackName"), f"{ns}-vps"
    )
    values["pulumi_runner_fleet_stack_name"] = _stringify(
        data.get("pulumiRunnerFleetStackName"), f"{ns}-runner-fleet"
    )

    # GitHub CI OIDC keys (registry stack template). The repo slug comes
    # from the project's `github` capability; empty renders the registry
    # stack without CI federation resources. The manage flag exists for a
    # second project in the SAME AWS account: the GitHub OIDC provider is
    # an account singleton, so exactly one project's registry stack
    # creates it (`ci_oidc_manage_provider` default true) and any other
    # declares false to reference it by ARN.
    github = settings.capabilities.get("github", {})
    owner = _stringify(github.get("repo_owner"))
    repo = _stringify(github.get("repo_name"))
    values["github_repo_slug"] = f"{owner}/{repo}" if owner and repo else ""
    manage_default = github.get("ci_oidc_manage_provider")
    values["manage_github_oidc_provider"] = _stringify(
        manage_default if manage_default is not None else True
    )

    values.update(
        runner_fleet_values(settings, fallback_repo=values["github_repo_slug"])
    )

    return values


def render_pulumi_stack_yaml(template_path: Path, values: Dict[str, str]) -> str:
    """Substitute placeholders into Pulumi stack YAML template content."""
    # Import here to avoid a circular import: project_renderer imports us.
    from .project_renderer import render_template
    return render_template(template_path.read_text(), values)


def _domain_txt_records_json(context: Dict[str, object]) -> str:
    domain_txt_records = context.get("domainTxtRecords")
    if not isinstance(domain_txt_records, list):
        domain_txt_records = []
    return json_helper.dumps_compact(domain_txt_records).replace("'", "''")


def _domain_mx_records_json(context: Dict[str, object]) -> str:
    domain_mx_records = context.get("domainMxRecords")
    if not isinstance(domain_mx_records, list):
        domain_mx_records = []
    return json_helper.dumps_compact(domain_mx_records).replace("'", "''")


def _copy_template_files(
    src_dir: Path, dst_dir: Path, files: List[str], write: bool,
) -> None:
    """Copy verbatim template files from src_dir to dst_dir.

    Python program files are byte-identical between source and destination.
    No header prepend, no placeholder substitution — operator's ``diff -q``
    must report no change.
    """
    for name in files:
        src = src_dir / name
        if not src.is_file():
            continue
        if write:
            dst = dst_dir / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            print(f"Rendered: {dst}", file=sys.stderr)
        else:
            print(f"--- infra/{name} ---")
            print(src.read_text())


# Program files copied verbatim into every project's infra/ regardless of the
# declared stack set: the stack-name dispatcher and the Pulumi dep manifest.
# Per-stack program modules (webapp_<type>_stack.py) are added on top of these
# from _STACK_TYPE_SPECS for each declared stack.
_SHARED_PROGRAM_FILES = (
    "__main__.py",
    "requirements.txt",
)
_ENVIRONMENT_PROGRAM_FILES = (
    "webapp_vps_stack.py",
    "webapp_database_stack.py",
    "webapp_api_stack.py",
    "webapp_distribution_stack.py",
    "webapp_environment_stack.py",
)
_RUNNER_FLEET_PROGRAM_FILES = (
    "webapp_runner_fleet_internals.py",
    "webapp_runner_idle_reaper.py",
)


def render_pulumi_artifacts(
    project: str,
    values: Dict[str, str],
    project_root: Path,
    proj_dir: Path,
    write: bool,
    settings: ProjectRendererSettings | None = None,
) -> None:
    """Render ``Pulumi.yaml`` + one stack YAML per declared stack type, and
    copy the shared + per-stack program modules under ``<proj_dir>/infra/``.

    The declared stack set comes from ``gather_pulumi_stacks`` (DB-backed site
    settings, default infra+vps). YAML files render with placeholder
    substitution; program modules copy verbatim (no header, no substitution) so
    the source-to-destination diff stays empty.
    """
    infra_src = project_root / "templates" / "webapp" / "infra"
    infra_dst = proj_dir / "infra"

    if not infra_src.is_dir():
        return

    # Pulumi.yaml — rendered with substitution (no-op today; source has no
    # placeholders, but we still route through render_template so the source
    # may grow placeholders in the future).
    pulumi_yaml_src = infra_src / "Pulumi.yaml"
    if pulumi_yaml_src.is_file():
        from .project_renderer import render_template
        rendered = render_template(pulumi_yaml_src.read_text(), values)
        if write:
            infra_dst.mkdir(parents=True, exist_ok=True)
            (infra_dst / "Pulumi.yaml").write_text(rendered)
            print(f"Rendered: {infra_dst / 'Pulumi.yaml'}", file=sys.stderr)
        else:
            print("--- infra/Pulumi.yaml ---")
            print(rendered)

    # One Pulumi.<project>-<type>.yaml per declared stack type, rendered with
    # substitution from the type's config template. When the destination file
    # already exists and carries operator-set state lines (set by `pulumi stack
    # init --secrets-provider`), preserve those lines so a re-render after stack
    # init does not strip the secrets provider configuration; a fresh render
    # (per-run scratch dirs have no prior file) falls back to the durable
    # environment-settings home (_operator_state_lines_from_settings).
    # Template-owned content (the `config:` block) is still rewritten from the
    # template — but a direct hand-edit of a config value (rather than via
    # DB-backed renderer settings) is loudly warned about before it is
    # overwritten (_warn_on_config_divergence).
    if settings is None:
        settings = load_project_renderer_settings(project)
    context = _pulumi_context_from_settings(settings)
    values = dict(values)
    values.setdefault("domain_txt_records_json", _domain_txt_records_json(context))
    values.setdefault("domain_mx_records_json", _domain_mx_records_json(context))
    program_files: List[str] = list(_SHARED_PROGRAM_FILES)
    stack_types = gather_pulumi_stacks(project, project_root, settings)
    domain_stack_owns_domain_records = "domain" in stack_types
    for stack_type in stack_types:
        program_file, config_tmpl_name = STACK_TYPE_SPECS[stack_type]
        # Honor an explicit per-stack name override (infra/vps carry one in the
        # values dict for backward compat); otherwise compose <project>-<type>.
        stack_key = stack_type.replace("-", "_")
        stack_name = (
            values.get(f"pulumi_{stack_key}_stack_name")
            or f"{settings.deploy_namespace}-{stack_type}"
        )
        stack_template = infra_src / config_tmpl_name
        if stack_template.is_file():
            # The domain config template substitutes {{manage_registration}},
            # which is not part of the shared values dict — inject it from the
            # project context (default "false": zone created, registration
            # pending the operator's console purchase step).
            stack_values = values
            if stack_type == "domain":
                stack_values = dict(values)
                stack_values["import_zone_id"] = str(
                    context.get("importZoneId", "") or ""
                )
                stack_values["manage_registration"] = (
                    "true" if context.get("manageRegistration") else "false"
                )
                stack_values["domain_txt_records_json"] = values.get(
                    "domain_txt_records_json", "[]"
                )
                stack_values["domain_mx_records_json"] = values.get(
                    "domain_mx_records_json", "[]"
                )
            elif stack_type == "registry":
                # The registry config template substitutes {{repository_name}},
                # which is not part of the shared values dict — inject it from
                # the project context (default "<project>-core", matching the
                # entrypoint's config default).
                stack_values = dict(values)
                stack_values["repository_name"] = (
                    str(context.get("containerRepositoryName", "") or "")
                    or f"{settings.deploy_namespace}-core"
                )
            elif stack_type == "infra" and domain_stack_owns_domain_records:
                stack_values = dict(values)
                stack_values["domain_txt_records_json"] = "[]"
                stack_values["domain_mx_records_json"] = "[]"
            rendered = render_pulumi_stack_yaml(stack_template, stack_values)
            out_name = f"Pulumi.{stack_name}.yaml"
            out_path = infra_dst / out_name
            # Existing-file lines win (operator's live edits), then the
            # settings fallback; otherwise render without them and let
            # pulumi error loudly.
            preserved = (
                _preserve_operator_state_lines(out_path)
                or _operator_state_lines_from_settings(settings, stack_name)
            )
            _warn_on_config_divergence(project, out_path, rendered)
            final_content = preserved + rendered if preserved else rendered
            if write:
                infra_dst.mkdir(parents=True, exist_ok=True)
                out_path.write_text(final_content)
                print(f"Rendered: {out_path}", file=sys.stderr)
            else:
                print(f"--- infra/{out_name} ---")
                print(final_content)
        if program_file not in program_files:
            program_files.append(program_file)
        if (
            stack_type in {"domain", "infra"}
            and "webapp_dns_records.py" not in program_files
        ):
            program_files.append("webapp_dns_records.py")
        if stack_type == "infra" and "webapp_distribution_stack.py" not in program_files:
            program_files.append("webapp_distribution_stack.py")
        if stack_type == "runner-fleet":
            for program_file in _RUNNER_FLEET_PROGRAM_FILES:
                if program_file not in program_files:
                    program_files.append(program_file)

    instance_template = infra_src / "Pulumi.environment-stack.yaml.tmpl"
    instances = gather_pulumi_stack_instances(project, project_root, settings)
    for instance in instances:
        if not instance_template.is_file():
            raise FileNotFoundError(
                f"Pulumi stackInstances for {project} require {instance_template}"
            )
        stack_values = instance_template_values(instance, values)
        rendered = render_pulumi_stack_yaml(instance_template, stack_values)
        out_name = f"Pulumi.{instance.name}.yaml"
        out_path = infra_dst / out_name
        preserved = (
            _preserve_operator_state_lines(out_path)
            or _operator_state_lines_from_settings(settings, instance.name)
        )
        _warn_on_config_divergence(project, out_path, rendered)
        final_content = preserved + rendered if preserved else rendered
        if write:
            infra_dst.mkdir(parents=True, exist_ok=True)
            out_path.write_text(final_content)
            print(f"Rendered: {out_path}", file=sys.stderr)
        else:
            print(f"--- infra/{out_name} ---")
            print(final_content)
    if instances:
        for program_file in _ENVIRONMENT_PROGRAM_FILES:
            if program_file not in program_files:
                program_files.append(program_file)

    # Program modules — copied verbatim (shared files + each declared stack's
    # module).
    _copy_template_files(infra_src, infra_dst, program_files, write)
