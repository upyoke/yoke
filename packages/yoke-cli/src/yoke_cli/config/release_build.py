"""Prove which exact Yoke build is installed against its published release.

The installed wheel records the full commit it was built from
(:func:`install_binding.detect` reads ``scm_version.json``). The release
tree publishes, for the same version, the commit its artifacts were built
from (``migration-history.json``) and every wheel's sha256
(``release-records.json``). :func:`verify_installed` compares the two commits
and returns the published wheel hashes; it stores nothing.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from yoke_cli.self_host import release_target


class ReleaseBuildError(RuntimeError):
    """The installed build cannot be proven against its published release."""


def verify_installed(
    *, version: str, source_commit: str, base_url: str
) -> list[dict[str, str]]:
    """Return the release's wheel hashes once its commit matches the install.

    Refuses with a named reason when the installed wheel carries no commit,
    the release publishes no usable record, or the commits differ.
    """
    reinstall = (
        "reinstall that exact release from this machine's distribution "
        f"origin: curl -fsSL {base_url}/install | "
        f"YOKE_INSTALL_BASE_URL={base_url} sh -s -- --version {version}"
    )
    if not source_commit:
        raise ReleaseBuildError(
            f"installed_source_commit_unavailable: the installed Yoke {version} "
            "wheel records no build commit in scm_version.json; " + reinstall
        )
    release_url = f"{base_url}/dist/releases/{urllib.parse.quote(version, safe='')}"
    try:
        manifest = release_target.fetch_json(
            f"{release_url}/migration-history.json",
            f"Yoke {version} release manifest",
        )
        records = release_target.fetch_json(
            f"{release_url}/release-records.json",
            f"Yoke {version} release records",
            list,
        )
    except release_target.ReleaseTargetError as exc:
        raise ReleaseBuildError(
            f"release_record_unavailable: {exc}. Check this machine's "
            f"distribution origin ({base_url}) with `yoke settings get "
            "distribution`, then "
            "rerun `yoke update --check`."
        ) from exc
    artifact = manifest.get("artifact")
    published = (
        str(artifact.get("source_commit") or "").strip()
        if isinstance(artifact, dict)
        else ""
    )
    if published != source_commit:
        raise ReleaseBuildError(
            f"installed_build_mismatch: the installed Yoke {version} was built "
            f"from {source_commit}, but release {version} at {base_url} was "
            f"built from {published or '<missing>'}; " + reinstall
        )
    return [_wheel(record, version) for record in records]


def _wheel(record: Any, version: str) -> dict[str, str]:
    filename = str(record.get("filename") or "") if isinstance(record, dict) else ""
    sha256 = str(record.get("sha256") or "") if isinstance(record, dict) else ""
    if not filename or not sha256:
        raise ReleaseBuildError(
            f"release_record_unavailable: Yoke {version} release records list "
            "a wheel without filename and sha256; retry after the release "
            "channel is healthy."
        )
    return {"filename": filename, "sha256": sha256}


__all__ = ["ReleaseBuildError", "verify_installed"]
