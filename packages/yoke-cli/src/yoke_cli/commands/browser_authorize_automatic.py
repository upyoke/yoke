"""Profile reset and automatic-site authorization without a human window."""

from dataclasses import replace

from yoke_cli.commands.browser_authorize_self_host import authorize_token_sites
from yoke_cli.config import browser_profile
from yoke_harness import browser_identity_check
from yoke_harness.browser_automatic_sign_in import sign_in_expired_sites


def reset_profile(client, runtime, project, identity):
    from yoke_harness.browser_human_gate import refuse_during_human_gate
    from yoke_harness.browser_live_profile import require_closed_profile

    refuse_during_human_gate(runtime.runtime_dir)
    profile = browser_profile.authorized_profile_dir(project, identity=identity.name)
    if profile:
        browser_identity_check.stop_profile_daemon(client, profile)
        require_closed_profile(profile)
    return browser_profile.remove_profile_dir(project, identity=identity.name)


def _automatic(site):
    return site.sign_in is not None or site.token_link


def authorize_automatic(client, runtime, project, identity, expired, connection=None):
    if not any(_automatic(site) for site in expired):
        return None, expired
    # authorize has already classified the sites. Pass that result rather than
    # probing twice before any credentials are typed.
    sites = [
        dict(
            site=s.site,
            state="expired" if s in expired else "signed_in",
            detail="declared sign-in check",
            origin=s.origin,
            account=s.account,
        )
        for s in identity.sites
    ]
    sites = sign_in_expired_sites(client, runtime, project, identity, sites)
    if any(s.token_link for s in expired):
        sites = authorize_token_sites(client, runtime, project, identity, sites, connection)
    return sites, [s for s in expired if not _automatic(s)]


def check_after_window(check, client, runtime, project, identity, automatic_sites):
    if automatic_sites is None:
        return check(client, runtime, project, identity)
    human = replace(
        identity, sites=tuple(s for s in identity.sites if not _automatic(s))
    )
    outcomes = {s["site"]: s for s in check(client, runtime, project, human)}
    outcomes.update(
        {
            s["site"]: s
            for s in automatic_sites
            if any(c.site == s["site"] and _automatic(c) for c in identity.sites)
        }
    )
    return [outcomes[s.site] for s in identity.sites]
