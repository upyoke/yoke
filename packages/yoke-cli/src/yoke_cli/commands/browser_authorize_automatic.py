"""Profile reset and automatic-site authorization without a human window."""

from dataclasses import replace

from yoke_cli.config import browser_profile
from yoke_harness import browser_identity_check
from yoke_harness.browser_automatic_sign_in import sign_in_expired_sites


def reset_profile(client, project, identity):
    profile = browser_profile.authorized_profile_dir(project, identity=identity.name)
    if profile:
        browser_identity_check.stop_profile_daemon(client, profile)
    browser_profile.remove_profile_dir(project, identity=identity.name)


def authorize_automatic(client, runtime, project, identity, expired):
    if not any(site.sign_in for site in expired):
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
    return sites, [s for s in expired if s.sign_in is None]


def check_after_window(check, client, runtime, project, identity, automatic_sites):
    if automatic_sites is None:
        return check(client, runtime, project, identity)
    human = replace(
        identity, sites=tuple(s for s in identity.sites if s.sign_in is None)
    )
    outcomes = {s["site"]: s for s in check(client, runtime, project, human)}
    outcomes.update(
        {
            s["site"]: s
            for s in automatic_sites
            if any(c.site == s["site"] and c.sign_in for c in identity.sites)
        }
    )
    return [outcomes[s.site] for s in identity.sites]
