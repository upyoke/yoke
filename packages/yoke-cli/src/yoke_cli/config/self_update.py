"""Client-local logic behind ``yoke update``.

Reruns the official public installer (onboarding disabled) against this
machine's already-configured distribution origin and channel, verifies the
installed version before and after, and repairs the git credential helper
that reinstall wipes from site-packages (``uv tool install --reinstall``
rebuilds the tool virtualenv from the wheel, discarding the content-addressed
bundle :mod:`yoke_cli.config.github_git_credentials` wrote there at runtime,
while the git config that still names that path survives untouched).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from yoke_cli.config import github_repo_helper_reconnect, install_binding
from yoke_cli.self_host import release_target

VERSION_PROBE_TIMEOUT_SECONDS = 30.0
_RUN = subprocess.run


class SelfUpdateError(RuntimeError):
    """A safe, named ``yoke update`` refusal or failure."""


def run_update(*, channel: str | None = None) -> dict[str, Any]:
    """Rerun the official installer for this machine, then verify and repair."""

    binding = install_binding.detect()
    if binding["kind"] == install_binding.KIND_SOURCE_CHECKOUT:
        raise SelfUpdateError(
            "yoke update does not run against a source checkout "
            f"({binding['checkout_root']}). Update this Yoke source tree "
            "with your normal git workflow instead of reinstalling a "
            "packaged release over it."
        )
    old_version = binding["version"]
    if not old_version:
        raise SelfUpdateError(
            "could not determine the installed Yoke version; repair with "
            "the public installer (curl -fsSL https://upyoke.com/install | "
            "sh) before running `yoke update`"
        )
    yoke_bin = shutil.which("yoke")
    if not yoke_bin:
        raise SelfUpdateError("could not resolve the `yoke` executable on PATH")

    try:
        target = release_target.channel_release_target(channel=channel)
    except release_target.ReleaseTargetError as exc:
        raise SelfUpdateError(f"could not resolve the release channel: {exc}") from exc

    if target.version == old_version:
        # `uv tool install --reinstall --force` wipes and rebuilds the tool
        # venv even when the version is unchanged, so skip that cost here —
        # this process's own site-packages is untouched, and repairing the
        # credential helper in place is cheap and always safe to retry.
        repair = github_repo_helper_reconnect.restore_missing_bundle(None)
        return _result(old_version, old_version, target, repair)

    try:
        installer_bytes = release_target.fetch_installer(target)
    except release_target.ReleaseTargetError as exc:
        raise SelfUpdateError(f"could not fetch the Yoke installer: {exc}") from exc
    try:
        completed = release_target.run_installer(target, installer_bytes)
    except release_target.ReleaseTargetError as exc:
        raise SelfUpdateError(str(exc)) from exc
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout or "").strip()[-2048:]
        raise SelfUpdateError(
            f"the Yoke installer failed (exit {completed.returncode}): "
            f"{diagnostic or 'no diagnostic output'}"
        )

    new_version = _probe_version(yoke_bin)
    if new_version != target.version:
        raise SelfUpdateError(
            "the Yoke installer reported success, but the freshly installed "
            f"`yoke --version` reports {new_version!r}, not the requested "
            f"{target.version!r}"
        )
    repair = _restore_bundle_via_binary(yoke_bin)
    return _result(old_version, new_version, target, repair)


def _result(
    old_version: str,
    new_version: str,
    target: release_target.ReleaseTarget,
    repair: dict[str, Any],
) -> dict[str, Any]:
    return {
        "old_version": old_version,
        "new_version": new_version,
        "already_current": new_version == old_version,
        "channel": target.channel,
        "base_url": target.base_url,
        "credential_helper_configured": repair.get("configured"),
        "credential_helper_repaired": repair.get("repaired"),
        "credential_helper_error": repair.get("error"),
    }


def _probe_version(yoke_bin: str) -> str:
    completed = _RUN(
        (yoke_bin, "--version"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=VERSION_PROBE_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise SelfUpdateError(
            "the Yoke installer finished, but the freshly installed "
            "`yoke --version` failed: "
            f"{(completed.stderr or completed.stdout or '').strip()[-2048:]}"
        )
    return completed.stdout.strip()


def _restore_bundle_via_binary(yoke_bin: str) -> dict[str, Any]:
    # Re-invoke the freshly installed binary rather than repair in this
    # process: the reinstall just rebuilt this interpreter's own
    # site-packages on disk, and if it also picked up a different Python
    # minor version this process's own site path no longer names what the
    # fresh install actually wrote.
    completed = _RUN(
        (yoke_bin, "github", "credential-helper", "refresh", "--json"),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=VERSION_PROBE_TIMEOUT_SECONDS,
    )
    diagnostic = (completed.stderr or completed.stdout or "").strip()[-2048:]
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or "configured" not in payload:
        return {
            "configured": None,
            "repaired": False,
            "error": diagnostic or "credential helper refresh produced no result",
        }
    return payload


__all__ = ["SelfUpdateError", "run_update"]
