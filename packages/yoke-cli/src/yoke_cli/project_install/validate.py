"""Bundle-shape validation for ``yoke project install``.

Split from :mod:`project_install` (which owns install/refresh/uninstall
orchestration) to respect the authored-file line cap. Validates the
frozen bundle contract: schema pin, files/hooks shapes, the optional
``project_contract_files`` (seed-if-missing) and ``strategy_files``
(db-render) sections with their single understood install policies.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_cli.project_install import hooks as hooks_layer
from yoke_cli.project_install import git_hooks as git_hooks_layer
from yoke_cli.project_install import strategy as strategy_layer
from yoke_contracts.project_contract.install_error import ProjectInstallError
from yoke_cli.transport.installed_cli_staleness import update_recovery
from yoke_contracts.engine_version import local_handshake_version
from yoke_contracts.project_contract.install_bundle import BUNDLE_SCHEMA
from yoke_contracts.project_contract.install_policy import SEED_IF_MISSING
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.release_version import release_version


def _validate_bundle(bundle: Dict[str, Any]) -> None:
    if not isinstance(bundle, dict):
        raise ProjectInstallError("install bundle must be a JSON object")
    schema = bundle.get("bundle_schema")
    if schema != BUNDLE_SCHEMA:
        if isinstance(schema, int) and schema < BUNDLE_SCHEMA:
            raise ProjectInstallError(
                f"installed_manifest_bundle_unavailable: serving bundle_schema "
                f"{schema} predates required {BUNDLE_SCHEMA}; ask the control-plane "
                "operator to serve a release with managed harness manifests, "
                "then rerun yoke project refresh. No project files were changed."
            )
        raise ProjectInstallError(
            f"bundle_schema {schema!r} is not the supported {BUNDLE_SCHEMA}; "
            "upgrade this CLI (rerun the public installer) to match the env"
        )
    if not isinstance(bundle.get("yoke_version"), str) or not bundle["yoke_version"]:
        raise ProjectInstallError("bundle yoke_version must be a non-empty string")
    project_id = bundle.get("project_id")
    if (
        isinstance(project_id, bool)
        or not isinstance(project_id, int)
        or project_id <= 0
    ):
        raise ProjectInstallError("bundle project_id must be a positive integer")
    if not isinstance(bundle.get("project_slug"), str) or not bundle["project_slug"]:
        raise ProjectInstallError("bundle project_slug must be a non-empty string")
    files = bundle.get("files")
    from yoke_cli.project_install.skill_discovery import validate_links

    validate_links(bundle.get("skill_discovery_links"))
    if not isinstance(files, list) or not all(
        isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and isinstance(e.get("content"), str)
        for e in files
    ):
        raise ProjectInstallError(
            "bundle 'files' must be a list of {path, content} objects"
        )
    markdown = bundle.get("managed_markdown")
    targets = (markdown.get("targets") or []) if isinstance(markdown, dict) else []
    if isinstance(targets, list) and any(
        isinstance(e, dict) and e.get("path") in {"CLAUDE.md", "CODEX.md", "CURSOR.md"}
        for e in targets
    ):
        raise ProjectInstallError(
            "instruction_discovery_contract_unsupported: shared doctrine must "
            "target AGENTS.md only; rebuild the serving bundle"
        )
    hooks = bundle.get("hooks")
    if not isinstance(hooks, dict):
        raise ProjectInstallError(
            "bundle 'hooks' must carry claude_settings_hooks, codex_hooks, "
            "and cursor_hooks objects"
        )
    for key, settings_rel in hooks_layer.SETTINGS_FILE_BY_HOOKS_KEY.items():
        value = hooks.get(key)
        if value is None:
            hooks[key] = {}
        elif not isinstance(value, dict):
            raise ProjectInstallError(
                "bundle 'hooks' must carry claude_settings_hooks, "
                "codex_hooks, and cursor_hooks objects"
            )
        hooks_layer.validate_hooks_subtree(
            hooks[key],
            label=f"bundle hooks.{key}",
            entry_format=hooks_layer.hook_entry_format(settings_rel),
        )
    git_hooks_layer.git_hook_specs_from_bundle(bundle)
    # Optional with default []: servers predating the project contract emit
    # no 'project_contract_files'; the install still applies files + hooks.
    contract = bundle.get("project_contract_files") or []
    if not isinstance(contract, list) or not all(
        isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and isinstance(e.get("content"), str)
        for e in contract
    ):
        raise ProjectInstallError(
            "bundle 'project_contract_files' must be a list of "
            "{path, content, install_policy} objects"
        )
    unknown_policies = sorted(
        {
            str(e.get("install_policy"))
            for e in contract
            if e.get("install_policy") != SEED_IF_MISSING
        }
    )
    if unknown_policies:
        raise ProjectInstallError(
            "bundle names unsupported contract install_policy "
            f"{unknown_policies}; this CLI understands only "
            f"'{SEED_IF_MISSING}' — upgrade this CLI (rerun the public installer) "
            "to match the env"
        )
    # Optional with default []: servers predating per-project strategy
    # delivery emit no 'strategy_files'; the install still applies the rest.
    strategy = bundle.get("strategy_files") or []
    if not isinstance(strategy, list) or not all(
        isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and isinstance(e.get("content"), str)
        for e in strategy
    ):
        raise ProjectInstallError(
            "bundle 'strategy_files' must be a list of "
            "{path, content, install_policy} objects"
        )
    unknown_strategy_policies = sorted(
        {
            str(e.get("install_policy"))
            for e in strategy
            if e.get("install_policy") != strategy_layer.STRATEGY_INSTALL_POLICY
        }
    )
    if unknown_strategy_policies:
        raise ProjectInstallError(
            "bundle names unsupported strategy install_policy "
            f"{unknown_strategy_policies}; this CLI understands only "
            f"'{strategy_layer.STRATEGY_INSTALL_POLICY}' — upgrade this CLI "
            "(rerun the public installer) to match the env"
        )


def validate_bundle_for_project(
    bundle: Dict[str, Any],
    expected_project_id: int,
) -> None:
    """Validate bundle shape and bind its identity to the requested project."""
    _validate_bundle(bundle)
    if bundle["project_id"] != expected_project_id:
        raise ProjectInstallError(
            f"install bundle project_id {bundle['project_id']} does not match "
            f"requested project_id {expected_project_id}"
        )


class CliReleaseMismatch(ProjectInstallError):
    """Setup observed a different served release than this CLI runs.

    ``target`` is the served release as a downloadable version, or ``None``
    when the served value names no release this CLI can install.
    """

    def __init__(
        self, running: str, served: str, target: str | None, *, server: str = ""
    ) -> None:
        self.running = running
        self.served = served
        self.target = target
        self.server = server
        super().__init__(self.refusal())

    def refusal(self, cause: str = "") -> str:
        """The setup refusal, optionally naming why setup could not follow."""
        if self.target is None:
            recovery = (
                "ask the server operator to serve a downloadable CLI release, "
                "then resume setup"
            )
        else:
            recovery = f"{update_recovery(self.target)}, then resume this setup run"
        detail = (
            f"{self.server} serves {self.served!r}"
            if self.server
            else f"the server supplied a {self.served!r} project layer"
        )
        reason = f"setup_bundle_version_mismatch: this CLI is {self.running}, but {detail}."
        if cause:
            reason = f"{reason} Setup could not install that release itself: {cause}"
        return compose_refusal(reason, recovery=f"{recovery}.")


def validate_cli_release(bundle: Dict[str, Any]) -> None:
    """Refuse setup with a bundle built for a different installed CLI."""
    served = bundle.get("yoke_version")
    if not isinstance(served, str) or not served:
        raise ProjectInstallError(
            "setup_bundle_version_missing: the install bundle has no release "
            "version. Ask the server operator to rebuild it, then resume setup."
        )
    running = local_handshake_version()
    if not running or served == running:
        return
    try:
        target: str | None = release_version(served)
    except ValueError:
        target = None
    raise CliReleaseMismatch(running, served, target)


__all__ = [
    "CliReleaseMismatch",
    "_validate_bundle",
    "validate_bundle_for_project",
    "validate_cli_release",
]
