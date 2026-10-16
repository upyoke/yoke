"""Operator help for browser identity authorization."""

from yoke_cli.config.browser_profile_cookies import SIGN_IN_COOKIE_LIFETIME_DAYS

AUTHORIZE_HELP = """\
Sign one identity of a project in, but only where it has to be. An identity is
one persona's whole browser profile -- every site that persona uses, for
example a Google account, the product account and a payment provider
together. A project declares identities under names it chooses, each listing
its sites and a signed-in check per site, in its browser-control capability
settings; `default` always exists and is the project's original profile.

The command first checks every declared site headless on the identity's
profile and reports each one (`buyer: google ok, yoke ok, paypal expired`).
When all are signed in it returns at once and opens nothing. Otherwise it
opens a window with one tab per expired site, naming the identity, the site
and the account to use, then checks again after the window closes and fails
naming any site still signed out. A site whose check cannot be reached fails
without a window: a sign-in cannot fix it. An identity that declares no sites
has nothing to check, so the window opens as it always did.

While the window is open no automated browser runs on this machine: every
browser daemon (any project, any profile) is stopped first, and starting one
is refused with `browser_human_gate_active` until the window closes. Cases and
walkers start their daemon again on their next command.

The window is a directly spawned browser process, never an automated one.
Google's sign-in refuses an automation-controlled browser ("Couldn't sign you
in. This browser or app may not be secure"). It is the daemon's own Chromium,
launched with the daemon's own cookie-encryption switches, because Chromium
drops any stored cookie it cannot decrypt when it opens a profile.

Close every authorization window to finish. On macOS, where Chromium may stay
running without a window, Yoke asks it to shut down after the last window
closes. If no macOS window opens in 30 seconds, or the browser runs for 30
minutes, the command stops it and names the condition; if it still holds the
profile 10 seconds later, quit the named PID and rerun without --reset.

Worked examples:

  yoke browser authorize                          # default identity, this checkout
  yoke browser authorize --project yoke --identity admin
  yoke browser authorize --project P --identity admin --machine Test-Mac
  yoke browser verify --project yoke --identity admin   # check without a window

With --machine, run on the operator workstation connected to the control
plane. Yoke reads browser-control settings here, checks the named Test Machine
lease, and runs this same command in its GUI session. A Linux or Windows WSL
machine with a registered RDP desktop opens in the same FreeRDP viewer as
`yoke test-machine desktop-access --view`: a window titled
"Yoke desktop: MACHINE" appears, you sign in with the identity's declared
account, and the viewer closes when verification finishes. Close the browser
window when done. If no viewer route or FreeRDP client is available, the
command prints the exact desktop-access command and its recovery, then still
waits for you to sign in on that desktop. macOS Screen Sharing uses the
printed command without --view. A machine leased by another session refuses
until released. Without --machine, this host keeps local behavior. Without a
remote route, --declarations-json still supplies settings locally.

Each identity's profile is kept with the project's machine-local capability
secrets at owner-only permissions, keyed by project slug and identity name. On
a Test Machine that keeps live identities (~/.yoke-browser-identities), the
profile is that live store entry, so a full reset keeps the sign-in.

Session cookies (no expiry) are given an explicit {lifetime}-day expiry when the
window closes, so the sign-in survives Chromium reopening the profile.

  yoke browser authorize --identity admin --reset

deletes that identity's profile and opens a fresh window for every declared
site; other identities are untouched.

Exit codes: 0 signed in (window opened or not needed); 1 the window could not
be opened, a site could not be checked, or a site is still signed out;
2 prerequisite failure (browser runtime missing, undeclared identity, bad
usage)."""
AUTHORIZE_HELP = AUTHORIZE_HELP.format(
    lifetime=SIGN_IN_COOKIE_LIFETIME_DAYS,
)
