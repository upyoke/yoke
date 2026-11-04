"""Profile reset and automatic-site authorization without a human window."""

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
