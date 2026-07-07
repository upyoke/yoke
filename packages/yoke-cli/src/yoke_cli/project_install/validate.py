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
from yoke_cli.project_install import strategy as strategy_layer
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.project_contract.install_bundle import BUNDLE_SCHEMA
from yoke_contracts.project_contract.install_policy import SEED_IF_MISSING


def _validate_bundle(bundle: Dict[str, Any]) -> None:
    schema = bundle.get("bundle_schema")
    if schema != BUNDLE_SCHEMA:
        raise ProjectInstallError(
            f"bundle_schema {schema!r} is not the supported {BUNDLE_SCHEMA}; "
            "upgrade this CLI (rerun the public installer) to match the env"
        )
    files = bundle.get("files")
    if not isinstance(files, list) or not all(
        isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and isinstance(e.get("content"), str)
        for e in files
    ):
        raise ProjectInstallError(
            "bundle 'files' must be a list of {path, content} objects"
        )
    hooks = bundle.get("hooks")
    if not isinstance(hooks, dict):
        raise ProjectInstallError(
            "bundle 'hooks' must carry claude_settings_hooks and codex_hooks "
            "objects"
        )
    for key in hooks_layer.SETTINGS_FILE_BY_HOOKS_KEY:
        value = hooks.get(key)
        if value is None:
            hooks[key] = {}
        elif not isinstance(value, dict):
            raise ProjectInstallError(
                "bundle 'hooks' must carry claude_settings_hooks and "
                "codex_hooks objects"
            )
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


__all__ = ["_validate_bundle"]
