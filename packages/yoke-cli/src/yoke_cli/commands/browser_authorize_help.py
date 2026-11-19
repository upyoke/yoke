"""Operator help for browser identity authorization."""

from yoke_cli.config.browser_profile_cookies import SIGN_IN_COOKIE_LIFETIME_DAYS

AUTHORIZE_HELP = """\
Sign one identity of a project in, but only where it has to be. An identity is
one persona's whole browser profile -- every site that persona uses, for
example a Google account, the product account and a payment provider
together. A project declares identities under names it chooses, each listing
its sites and a signed-in check per site, in its browser-control capability
settings; `default` always exists and is the project's original profile.

For a first-party test account, a site can declare sign_in.mode automatic with
a same-origin URL and fill/secret or click steps. Store each field on this
machine using `yoke projects capability secret set --project P --cap-type
browser-control --key sign-in.IDENTITY.SITE.FIELD --value-stdin` (or
--value-file FILE). Yoke signs expired automatic sites in headless without a
window or Keychain. Browser cases do this before their first step; verify
only checks and never types. Keep Google, Microsoft and MFA sites human by
omitting sign_in. Native Test Machine browser sign-in stays human.

The command first checks every declared site headless on the identity's
profile and reports each one (`buyer: google ok, yoke ok, paypal expired`).
With --url it always opens that URL, even when all sites are signed in,
so you can complete extra access checks. Without --url, when all are signed
in it returns at once and opens nothing. Otherwise it
signs automatic sites in, then opens a window with one tab per expired human site, naming the identity, the site
and the account to use, then checks again after the window closes and fails
naming any site still signed out. A site whose check cannot be reached fails
without a window: a sign-in cannot fix it. An identity that declares no sites
has nothing to check, so the window opens as it always did.

While the window is open no automated browser runs on this machine: every
browser daemon (any project, any profile) is stopped first, and starting one
is refused with `browser_human_gate_active`, naming the identity, project, PID
and how long the window has been open. Hand off to steering or the person at
that machine to finish or close that sign-in window, or quit the named PID,
then retry. Cases and walkers start their daemon again on their next command.

The window is a directly spawned browser process, never an automated one.
Google's sign-in refuses an automation-controlled browser ("Couldn't sign you
in. This browser or app may not be secure"). It is the daemon's own Chromium,
launched with the daemon's own cookie-encryption switches, because Chromium
drops any stored cookie it cannot decrypt when it opens a profile.

Close every authorization window to finish. On macOS, where Chromium may stay
running without a window, Yoke asks it to shut down after the last window
closes. If no macOS or Linux window opens in 30 seconds, or the browser runs
for 30 minutes, the command stops it and names the condition; if it still
holds the profile 10 seconds later, quit the named PID and rerun without
--reset.

Worked examples:

  yoke browser authorize                          # default identity, this checkout
  yoke browser authorize --project yoke --identity admin
  yoke browser authorize --project P --identity admin --test-machine Test-Mac
  yoke browser verify --project yoke --identity admin   # check without a window

With --test-machine, run on the operator workstation connected to the control
plane. Yoke reads browser-control settings here, checks the named Test Machine
lease, and runs this same command in its GUI session. It takes an unleased host
or borrows your own lease, starts stopped cloud machines and waits for SSH.
The lease stays held through sign-in and viewer cleanup; only a lease this
command acquired releases afterward, with stop-on-last-release. Before opening
a viewer it checks Yoke on the login-shell PATH; test_machine_yoke_missing
names the reset with --baseline shell-preconfigured needed to install it. A Linux,
native Windows or Windows WSL machine with a registered RDP desktop opens in the
same FreeRDP viewer as `yoke test-machine desktop-access --view`: a window titled
"Yoke desktop: MACHINE" appears, you sign in with the identity's declared
account, and the viewer closes when verification finishes. Close the browser
window when done. If no viewer route or FreeRDP client is available, the
command prints the exact desktop-access command and its recovery, then still
waits for you to sign in on that desktop. A macOS machine with a registered
VNC route opens in Screen Sharing from a Mac workstation, as with
desktop-access --view: paste the desktop password from the clipboard, which
Yoke clears after 60 seconds, and quit Screen Sharing after verification
finishes. A machine leased by another session refuses
until released. Without --test-machine, this host keeps local behavior. Without a
remote route, --declarations-json still supplies settings locally.

The identity profile is the Test Machine's only saved login: missions,
managed steps and the installer's approval link all open in it through
`yoke browser open`, so one sign-in per identity serves every browser use.
If default has no sites but other identities do, an omitted --identity refuses
with browser_identity_required and names the choices before opening any window.
Site, origin and account instructions print on the workstation before its viewer.
Linux remote progress streams while authorization runs, including verification;
--json reserves stdout for the final receipt and sends progress to stderr.
A connected Linux viewer refuses linux_desktop_viewer_connected: close the open
"Yoke desktop: MACHINE" viewer or let browser authorize finish, then retry.
Linux window detection requires xdotool and counts the windows of every
Chromium main process the launch started or that runs this profile, so a
launcher such as /usr/bin/chromium-browser whose child draws the window counts.

Each identity's profile is saved owner-only in the live identity store
~/.yoke-browser-identities/<project>/<identity>, outside ~/.yoke, which the
first authorization creates; a Test Machine's full reset keeps the sign-in.

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
