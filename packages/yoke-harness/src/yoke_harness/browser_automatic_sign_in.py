"""Headless, machine-local automatic sign-in shared by authorize and Browser QA."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from yoke_contracts.browser_identity import BrowserIdentity
from yoke_cli.config import browser_profile
from yoke_cli.config.capability_secrets import machine_capability_secret_path
from yoke_cli.config.browser_profile_cookies import (
    keep_sign_in_cookies,
    SignInCookieError,
)
from yoke_harness import browser_identity_check as checks


class AutomaticSignInError(RuntimeError):
    """A credential or sign-in failed, with no credential-bearing diagnostics."""


def _failed(site: str) -> AutomaticSignInError:
    return AutomaticSignInError(
        f"browser_automatic_sign_in_failed: site {site} did not pass its sign-in "
        "check. Check the test account and declared steps, then retry; for human "
        "sign-in remove sign_in from the site and run `yoke browser authorize`."
    )


def sign_in_expired_sites(
    client,
    runtime,
    project: str,
    identity: BrowserIdentity,
    sites: list[dict] | None = None,
) -> list[dict]:
    """Stop this profile's daemon, check, sign in expired automatic sites, recheck.

    The Python process resolves paths only. Credentials never cross argv, enter
    a manifest, or appear in evidence. Child output is always treated as private.
    """
    from yoke_harness.browser_human_gate import refuse_during_human_gate

    refuse_during_human_gate(runtime.runtime_dir)
    profile = browser_profile.authorized_profile_dir(project, identity=identity.name)
    if profile is not None:
        checks.stop_profile_daemon(client, profile)
    if sites is None:
        sites = checks.check_identity(
            identity,
            profile,
            node=runtime.node,
            runtime_dir=runtime.runtime_dir,
            env=runtime.env,
        )
    for site in identity.sites:
        if site.sign_in and any(
            s["site"] == site.site and s["state"] == checks.UNREACHABLE for s in sites
        ):
            raise _failed(site.site)
    expired = {s["site"] for s in sites if s["state"] == checks.EXPIRED}
    automatic = [s for s in identity.sites if s.sign_in and s.site in expired]
    if not automatic:
        return sites
    entries = []
    for site in automatic:
        secret_files = {}
        for step in site.sign_in.steps:
            if "secret" not in step:
                continue
            field = step["secret"]
            key = f"sign-in.{identity.name}.{site.site}.{field}"
            path = machine_capability_secret_path(project, "browser-control", key)
            if not path.is_file() or path.stat().st_size == 0:
                raise AutomaticSignInError(
                    f"browser_sign_in_secret_missing: site {site.site} needs {key}. "
                    "Store it on this machine with `yoke projects capability secret "
                    f"set --project {project} --cap-type browser-control --key {key} "
                    "--value-stdin` (or --value-file FILE), then retry."
                )
            secret_files[field] = str(path)
        entries.append(
            dict(
                site=site.site,
                origin=site.origin,
                probe=site.as_probe(),
                sign_in=dict(url=site.sign_in.url, steps=site.sign_in.steps),
                secret_files=secret_files,
            )
        )
    profile = browser_profile.ensure_profile_dir(project, identity=identity.name)
    try:
        with tempfile.TemporaryDirectory(prefix="yoke-browser-sign-in-") as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"sites": entries}), encoding="utf-8")
            manifest.chmod(0o600)
            result = subprocess.run(
                [
                    str(runtime.node),
                    str(runtime.runtime_dir / "src" / "authorize-automatic.js"),
                    str(profile),
                    str(manifest),
                ],
                cwd=runtime.runtime_dir,
                env=runtime.env,
                capture_output=True,
                text=True,
                timeout=checks.CHECK_TIMEOUT_SECONDS,
                check=False,
            )
            outcomes = (
                json.loads(result.stdout)["sites"] if result.returncode == 0 else []
            )
        by_site = {s["site"]: s["state"] for s in outcomes}
        for site in automatic:
            if by_site.get(site.site) != checks.SIGNED_IN:
                raise _failed(site.site)
        keep_sign_in_cookies(profile)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        SignInCookieError,
    ):
        raise _failed(automatic[0].site) from None
    # Use sanitized outcomes, not another raw probe that could echo credentials.
    return [
        dict(s, state=checks.SIGNED_IN, detail="automatic sign-in check passed")
        if s["site"] in expired and s["site"] in by_site
        else s
        for s in sites
    ]
