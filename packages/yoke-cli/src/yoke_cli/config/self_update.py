"""Client-local logic behind ``yoke update``.

Reruns the official public installer (onboarding disabled) against this
machine's already-configured distribution origin and channel, then verifies
the installed version. Reinstalling the git credential helper is the public
installer's own job (``packaging/public-installer/install.py``, run in-process
by ``curl | sh`` and here alike): it repairs the bundle every reinstall wipes
from site-packages, and enforces that repair as part of its own readiness --
a repair failure fails the installer itself, surfacing here as the existing
non-zero installer exit code. This module never repeats that repair for a
reinstall; it has no independent repair signal of its own to report once the
installer has succeeded. The one exception is the already-current fast path
below, which skips rerunning the installer entirely (to avoid the reinstall
cost) and so repairs in-process instead, since there is no installer run to
own that step here.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from yoke_cli.config import github_repo_helper_reconnect, install_binding
from yoke_cli.self_host import release_target

VERSION_PROBE_TIMEOUT_SECONDS = 30.0
_RUN = subprocess.run

# A successful reinstall carries no independent credential-helper signal:
# the installer performed and enforced that repair itself (a failure there
# is a non-zero installer exit, handled above as a SelfUpdateError).
_INSTALLER_OWNED_REPAIR: dict[str, Any] = {
    "configured": None,
    "repaired": None,
    "error": None,
}


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
        # Covers every installer-owned failure, credential-helper repair
        # included: the installer raises the same way a product-boundary
        # audit failure does, so its exit code is the one signal needed.
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
    return _result(old_version, new_version, target, _INSTALLER_OWNED_REPAIR)


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


__all__ = ["SelfUpdateError", "run_update"]
