"""Authorize a declared token-link site with the active self-host credential."""

from __future__ import annotations

import subprocess
from urllib.parse import urlsplit

from yoke_cli.config.self_host_browser_sign_in import (
    mint_self_host_sign_in_link,
    self_host_connection,
    self_host_sign_in_method,
    self_host_url,
)
from yoke_contracts.refusal_recovery import compose_refusal

_RETRY = "run `yoke browser authorize` again"
_REFUSALS = {
    "browser_sign_in_expired": "the single-use sign-in link expired",
    "browser_sign_in_used": "the single-use sign-in link was already used",
    "browser_sign_in_oidc_required": "the server requires company sign-in",
}
_OIDC_RECOVERY = (
    "Remove token-link from the site declaration and use the company's sign-in "
    "page when you run `yoke browser authorize`"
)


def _refusal(reason, recovery):
    return RuntimeError(compose_refusal(reason, recovery=recovery))


def _origin(url):
    try:
        parsed = urlsplit(url)
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        if parsed.scheme not in {"http", "https"} or "\\" in parsed.netloc:
            return None
        port = parsed.port if parsed.port is not None else {"http": 80, "https": 443}[parsed.scheme]
    except ValueError:
        return None
    return parsed.scheme, parsed.hostname, port


def token_site_connection(identity):
    sites = [site for site in identity.sites if site.token_link]
    if not sites:
        return None
    connection = self_host_connection()
    if connection is None:
        raise _refusal(
            "browser_sign_in_self_host_required: token-link sites require an active "
            "self-hosted connection on this machine",
            f"Select the connection with `yoke env use` or add it with `yoke connect`, then {_RETRY}",
        )
    origin = _origin(self_host_url(connection))
    for site in sites:
        if origin is None or origin != _origin(site.origin) or origin != _origin(site.probe_url):
            raise _refusal(
                f"browser_sign_in_origin_mismatch: site {site.site} and its probe must "
                "use the active self-hosted server's origin",
                f"Correct the declaration or select that server's connection, then {_RETRY}",
            )
    if self_host_sign_in_method(connection, recovery=_RETRY) == "oidc":
        raise _refusal(
            "browser_sign_in_oidc_required: the server requires company sign-in",
            _OIDC_RECOVERY,
        )
    return connection


def authorize_token_sites(client, runtime, project, identity, sites, connection):
    from yoke_cli.config import browser_profile
    from yoke_cli.config.browser_profile_cookies import SignInCookieError, keep_sign_in_cookies
    from yoke_harness import browser_identity_check as checks
    from yoke_harness.browser_human_gate import refuse_during_human_gate

    refuse_during_human_gate(runtime.runtime_dir)
    profile = browser_profile.ensure_profile_dir(project, identity=identity.name)
    checks.stop_profile_daemon(client, profile)
    outcomes = {outcome["site"]: outcome for outcome in sites}
    for site in identity.sites:
        if site.token_link and outcomes[site.site]["state"] == checks.EXPIRED:
            outcomes[site.site] = _authorize_site(
                runtime, profile, site, outcomes[site.site], connection
            )
    try:
        keep_sign_in_cookies(profile)
    except SignInCookieError:
        raise _refusal(
            "browser_sign_in_cookie_save_failed: could not retain the browser session",
            f"Check the identity profile permissions, then {_RETRY}",
        ) from None
    return [outcomes[site.site] for site in identity.sites]


def _authorize_site(runtime, profile, site, previous, connection):
    from yoke_harness.browser_automatic_sign_in import run_automatic_sign_in

    def entries():
        link = mint_self_host_sign_in_link(connection, recovery=_RETRY)
        if link is None:
            raise _refusal(
                "browser_sign_in_oidc_required: the server requires company sign-in",
                _OIDC_RECOVERY,
            )
        return [{"site": site.site, "probe": site.as_probe(), "token_link": link}]

    state = None
    try:
        results = run_automatic_sign_in(runtime, profile, entries, private=True)
        if isinstance(results, list) and len(results) == 1 and isinstance(results[0], dict):
            if results[0].get("site") == site.site:
                state = results[0].get("state")
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        pass
    if state == "signed_in":
        return dict(previous, state=state, detail="token-link sign-in check passed")
    if isinstance(state, str) and state in _REFUSALS:
        recovery = _OIDC_RECOVERY if state == "browser_sign_in_oidc_required" else _RETRY
        raise _refusal(f"{state}: {_REFUSALS[state]} for site {site.site}", recovery)
    raise _refusal(
        f"browser_token_link_sign_in_failed: site {site.site} did not pass its sign-in check",
        f"Check the server, browser runtime and declared probe, then {_RETRY}",
    )
