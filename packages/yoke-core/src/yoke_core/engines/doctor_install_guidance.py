"""Install readiness from existing project-layer and instruction diagnostics."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.machine_config.schema import mapped_checkouts
from yoke_cli import operating_layer_drift
from yoke_cli.config import machine_config, project_installed_layer
from yoke_cli.project_install import instruction_discovery
from yoke_cli.project_install.files import load_manifest
from yoke_core.engines.doctor_hc_launcher_authority import (
    _machine_launcher_env,
    hook_config_yoke_problems,
)
from yoke_core.tools.install_yoke_launcher_sweep import (
    canonical_shim_path,
    enumerate_shadow_installs,
)


def project_root(args) -> Path:
    from yoke_core.engines.doctor_https_compose import checkout_root_for_project

    root = checkout_root_for_project(str(args.project or ""))
    if root is None:
        raise ValueError(
            "INSTALL_CHECKOUT_MISSING: register the selected project's checkout with `yoke project register`."
        )
    return root


def hc_install_residue(conn, args, rec) -> None:
    try:
        root = project_root(args)
        canonical = canonical_shim_path()
        problems = hook_config_yoke_problems(root, canonical)
        if enumerate_shadow_installs(canonical=canonical, env=_machine_launcher_env()):
            problems.append("another Yoke launcher shadows the canonical install")
        manifest = load_manifest(root)
        if manifest is not None:
            expected = {
                str(project_id)
                for checkout, project_id in mapped_checkouts(
                    machine_config.load_config()
                )
                if Path(checkout).expanduser().resolve() == root.resolve()
            }
            if (
                manifest.get("project_id") is not None
                and str(manifest["project_id"]) not in expected
            ):
                problems.append("install manifest belongs to another project's binding")
        if problems:
            raise ValueError("; ".join(problems))
    except Exception as exc:
        rec.record(
            "install-residue",
            "No configuration from another install",
            "FAIL",
            f"INSTALL_RESIDUE: {exc}. Run `yoke setup` to inspect and repair the existing installation before retrying.",
        )
        return
    rec.record(
        "install-residue",
        "No configuration from another install",
        "PASS",
        "Launcher, hook commands and manifest project binding have no foreign install residue.",
    )


def hc_installed_guidance(conn, args, rec) -> None:
    try:
        root = project_root(args)
        layer = project_installed_layer.scan(root)
        if not layer.present:
            raise ValueError("no installed operating layer")
        version, origin = operating_layer_drift.running_identity()
        comparison = operating_layer_drift.compare_installed_layer(
            root,
            running_version=version,
            running_module_file=origin,
        )
        if (
            comparison is None
            or comparison.running.relationship != operating_layer_drift.RUNNING_EQUAL
        ):
            raise ValueError(
                "installed guidance release is missing, unknown, or differs from running code"
            )
    except Exception as exc:
        rec.record(
            "installed-guidance",
            "Installed guidance matches the running code",
            "FAIL",
            f"INSTALLED_GUIDANCE_UNVERIFIED: {exc}. Run `yoke project install` in the selected project checkout, then rerun Doctor.",
        )
        return
    rec.record(
        "installed-guidance",
        "Installed guidance matches the running code",
        "PASS",
        "Installed-layer receipt matches the running code; this proves configuration, not session delivery.",
    )


def hc_instruction_discovery(conn, args, rec) -> None:
    try:
        root = project_root(args)
        if (
            not (root / "AGENTS.md").is_file()
            or not (root / ".yoke/docs/agents/harness-discovery.md").is_file()
        ):
            raise ValueError(
                "canonical instructions or their discovery pointer are missing"
            )
        instruction_discovery.preflight(root)
    except Exception as exc:
        rec.record(
            "instruction-discovery",
            "Canonical instructions are reachable",
            "FAIL",
            f"INSTRUCTION_DISCOVERY_UNVERIFIED: {exc}. Repair the named instruction setting and run `yoke project install` in that checkout.",
        )
        return
    rec.record(
        "instruction-discovery",
        "Canonical instructions are reachable",
        "PASS",
        "Canonical instruction entry and discovery pointer are reachable; installed harness loading preflight passed.",
    )
