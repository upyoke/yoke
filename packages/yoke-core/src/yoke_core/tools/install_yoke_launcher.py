"""Canonical one-shot install for the venv-independent ``yoke`` launcher."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Optional

from yoke_core.tools import install_yoke_launcher_claude as _claude
from yoke_core.tools import install_yoke_launcher_core as _core
from yoke_core.tools import install_yoke_launcher_macos as _macos


InstallError = _core.InstallError
TargetChoice = _core.TargetChoice

TARGET_PRIORITY = _core.TARGET_PRIORITY
MIN_PYTHON = _core.MIN_PYTHON
YOKE_PACKAGE_NAME = _core.YOKE_PACKAGE_NAME
YOKE_EDITABLE_PACKAGE_NAMES = _core.YOKE_EDITABLE_PACKAGE_NAMES
LAUNCHER_FILENAME = _core.LAUNCHER_FILENAME
LAUNCHER_SOURCE = _core.LAUNCHER_SOURCE
PROBE_BYTES = _core.PROBE_BYTES
LAUNCHER_FINGERPRINT_IMPORT = _core.LAUNCHER_FINGERPRINT_IMPORT
LEGACY_LAUNCHER_FINGERPRINT_IMPORT = _core.LEGACY_LAUNCHER_FINGERPRINT_IMPORT

CLAUDE_APP_CONFIG_PATH = _claude.CLAUDE_APP_CONFIG_PATH
MACOS_PATHS_FILE = _macos.MACOS_PATHS_FILE
BREW_APPLE_SILICON_BIN = _macos.BREW_APPLE_SILICON_BIN

verify_python_version = _core.verify_python_version
verify_repo_root = _core.verify_repo_root
read_pyproject_deps = _core.read_pyproject_deps
run_pip_uninstall_old_yoke_packages = _core.run_pip_uninstall_old_yoke_packages
cleanup_stale_editable_yoke_metadata = _core.cleanup_stale_editable_yoke_metadata
refuse_foreign_binary = _core.refuse_foreign_binary
verify_path_includes = _core.verify_path_includes
run_verification = _core.run_verification
_is_externally_managed = _core._is_externally_managed


def run_pip_install_deps(
    cwd: Path,
    *,
    allow_system_packages: bool = True,
    stream=None,
) -> None:
    original_probe = _core._is_externally_managed
    original_cleanup = _core.cleanup_stale_editable_yoke_metadata
    _core._is_externally_managed = _is_externally_managed
    _core.cleanup_stale_editable_yoke_metadata = cleanup_stale_editable_yoke_metadata
    try:
        _core.run_pip_install_deps(
            cwd,
            allow_system_packages=allow_system_packages,
            stream=stream,
        )
    finally:
        _core._is_externally_managed = original_probe
        _core.cleanup_stale_editable_yoke_metadata = original_cleanup


def auto_detect_target(
    home: Path,
    override: Optional[str] = None,
    force_user: bool = False,
    force_system: bool = False,
    env_path: Optional[str] = None,
) -> TargetChoice:
    original_priority = _core.TARGET_PRIORITY
    _core.TARGET_PRIORITY = TARGET_PRIORITY
    try:
        return _core.auto_detect_target(
            home=home,
            override=override,
            force_user=force_user,
            force_system=force_system,
            env_path=env_path,
        )
    finally:
        _core.TARGET_PRIORITY = original_priority


def write_launcher(
    target_path: Path,
    source: Optional[Path] = None,
    *,
    default_home: Optional[Path] = None,
) -> None:
    launcher_source = source if source is not None else LAUNCHER_SOURCE
    _core.write_launcher(target_path, source=launcher_source, default_home=default_home)


def configure_claude_app_bypass_permissions(
    *,
    config_path: Optional[Path] = None,
    stream=None,
) -> bool:
    _claude.CLAUDE_APP_CONFIG_PATH = CLAUDE_APP_CONFIG_PATH
    return _claude.configure_claude_app_bypass_permissions(
        config_path=config_path,
        stream=stream,
    )


def _sync_macos_config() -> None:
    _macos.MACOS_PATHS_FILE = MACOS_PATHS_FILE
    _macos.BREW_APPLE_SILICON_BIN = BREW_APPLE_SILICON_BIN


def _macos_path_fix_skip_reason() -> Optional[str]:
    _sync_macos_config()
    return _macos._macos_path_fix_skip_reason()


def configure_macos_path_for_homebrew(
    *,
    paths_file: Optional[Path] = None,
    brew_bin: Optional[Path] = None,
    stream=None,
) -> bool:
    _sync_macos_config()
    return _macos.configure_macos_path_for_homebrew(
        paths_file=paths_file,
        brew_bin=brew_bin,
        stream=stream,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_yoke_launcher",
        description="Install the venv-independent yoke launcher.",
    )
    parser.add_argument(
        "--target-dir",
        help="Install-target directory (overrides auto-detect).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--user", action="store_true", help="Force ~/.local/bin target."
    )
    group.add_argument(
        "--system",
        action="store_true",
        help="Force /usr/local/bin target (may prompt for sudo at write time).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing non-Yoke binary at the target path.",
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Skip 'pip install <deps>' (useful when deps are already installed).",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip 'yoke --version' / 'yoke status' verification.",
    )
    parser.add_argument(
        "--verify-env",
        help=(
            "Set YOKE_ENV for the post-install verification commands. "
            "Defaults to the invoking environment when omitted."
        ),
    )
    parser.add_argument(
        "--no-system-packages",
        action="store_true",
        help=(
            "Refuse to install into an EXTERNALLY-MANAGED Python (opt out of "
            "auto-setting PIP_BREAK_SYSTEM_PACKAGES=1). Use a venv instead."
        ),
    )
    parser.add_argument(
        "--skip-claude-config",
        action="store_true",
        help=(
            "Skip the Claude.app bypass-permissions preference patch. macOS "
            "only — no-op on other platforms. The patch only sets "
            "bypassPermissionsModeEnabled=true when the key is absent; "
            "explicit-False values are always respected."
        ),
    )
    parser.add_argument(
        "--skip-macos-path-fix",
        action="store_true",
        help=(
            "Skip the macOS /etc/paths prepend of /opt/homebrew/bin. macOS "
            "only — no-op on other platforms or when already configured. "
            "Without this fix, GUI apps (Claude.app/Codex.app) inherit "
            "/etc/paths order which puts /usr/bin before /opt/homebrew/bin "
            "and resolve `python3` to Apple's 3.9. Requires sudo when applied."
        ),
    )
    return parser


def install(
    *,
    cwd: Optional[Path] = None,
    home: Optional[Path] = None,
    target_dir: Optional[str] = None,
    force_user: bool = False,
    force_system: bool = False,
    force: bool = False,
    skip_pip: bool = False,
    skip_verify: bool = False,
    verify_env: Optional[str] = None,
    no_system_packages: bool = False,
    skip_claude_config: bool = False,
    skip_macos_path_fix: bool = False,
    stream=None,
) -> TargetChoice:
    """Run the install steps. Returns the chosen target."""
    out = stream if stream is not None else sys.stdout
    verify_python_version()
    cwd = (cwd or Path.cwd()).resolve()
    verify_repo_root(cwd)
    if not skip_pip:
        run_pip_install_deps(
            cwd,
            allow_system_packages=not no_system_packages,
            stream=out,
        )
    home = home or Path(os.environ.get("YOKE_HOME") or os.path.expanduser("~/yoke"))
    choice = auto_detect_target(
        home=home,
        override=target_dir,
        force_user=force_user,
        force_system=force_system,
    )
    target_path = choice.path / LAUNCHER_FILENAME
    refuse_foreign_binary(target_path, force=force)
    write_launcher(target_path, default_home=home)
    verify_path_includes(choice.path, stream=out)
    if not skip_verify:
        run_verification(verify_env=verify_env, stream=out)
    if not skip_claude_config:
        configure_claude_app_bypass_permissions(stream=out)
    if not skip_macos_path_fix:
        configure_macos_path_for_homebrew(stream=out)
    py_version = ".".join(str(x) for x in sys.version_info[:3])
    deps_dir = sysconfig.get_path("purelib")
    out.write(
        f"\nyoke installed.\n"
        f"  Launcher:  {target_path}\n"
        f"  Python:    {sys.executable} (Python {py_version})\n"
        f"  Deps in:   {deps_dir}\n"
    )
    return choice


def main(argv: Optional[list] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        install(
            target_dir=args.target_dir,
            force_user=args.user,
            force_system=args.system,
            force=args.force,
            skip_pip=args.skip_pip,
            skip_verify=args.skip_verify,
            verify_env=args.verify_env,
            no_system_packages=args.no_system_packages,
            skip_claude_config=args.skip_claude_config,
            skip_macos_path_fix=args.skip_macos_path_fix,
        )
    except InstallError as exc:
        sys.stderr.write(f"install_yoke_launcher: {exc}\n")
        return 2
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"install_yoke_launcher: subprocess failed: {exc}\n")
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
