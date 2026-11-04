# Browser sign-in identities

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Browser identities
<!-- /yoke:breadcrumbs -->

A browser identity is one persona's whole browser profile: every site that
persona uses, signed in together (for example a Google account, the product
account and a payment provider). A project declares as many identities as its
tests need, under names it chooses. Each identity has its own profile, so
signing a second account in never overwrites the first. Within one profile a
site holds one active login, as in a real browser; a test that needs two
accounts on the same site at once uses two identities. `default` always exists
and is the project's original single profile, so a project that declares
nothing behaves as before.

## Declaring identities

Identities are nonsecret data in the project's `browser-control` capability
settings. Each site names its origin, optionally the account a human should
use, and a signed-in check: a URL plus either `signed_in_selector` (the page
shows that element and no sign-in wall) or `signed_in_status` (the URL,
requested with the profile's cookies and without following redirects, answers
that HTTP status). When a case lands on Google's account chooser, the runner
clicks the account recorded on that identity's `accounts.google.com` site.

```json
{"identities": {"buyer": {"sites": [
  {"site": "google", "origin": "https://accounts.google.com",
   "account": "buyer@example.com",
   "probe": {"url": "https://myaccount.google.com/", "signed_in_selector": "a[aria-label^='Google Account']"}},
  {"site": "shop", "origin": "https://shop.example.com",
   "probe": {"url": "https://shop.example.com/api/me", "signed_in_status": 200}}
]}}}
```

Set it with `yoke projects capability-settings set --project P --cap-type
browser-control`. Credentials outside the browser (CLI tokens, API keys) stay on
the capability-secrets surface; an identity holds only browser sessions.

## Checking and signing in

```text
yoke browser verify --project P --identity buyer        # buyer: google ok, shop expired
yoke browser authorize --project P --identity buyer     # window only for expired sites
```

`verify` checks every declared site headless and reports each one. `authorize`
runs the same check first and returns at once when every site is signed in,
unless you supply `--url URL`. With `--url`, it always opens that URL so you can
complete an extra access check such as GitHub Confirm access. This also applies
to `--desktop-browser` and `--test-machine`.
Otherwise it signs expired automatic sites in headless, then opens one window
with a tab per expired human site, naming the identity,
the site and the account, and checks again after the window closes. A site
whose check cannot be reached fails by name: no sign-in fixes it.

If `default` declares no sites while other identities do, omitting `--identity`
refuses with `browser_identity_required` and names the choices before any window
opens. Choose the declared identity; site, origin and account instructions print
on the workstation before its viewer opens.
Linux remote authorization streams progress as it runs. JSON mode keeps stdout
for the final receipt and sends progress to stderr.

While a sign-in window is open no automated browser runs on the machine: every
browser daemon is stopped first, and a daemon start is refused with
`browser_human_gate_active`, naming the identity, project, PID and how long
the window has been open. Hand off to steering or the person at that machine
to finish or close that sign-in window, or quit the named PID, then retry.
Sign-in windows close after 30 minutes; managed Chromium gets 10 seconds to
quit before it is force-stopped. A gate marker older than 30 minutes plus
that shutdown margin is removed even if its recorded PID is still alive.

## Automatic sign-in for first-party test accounts

Use a dedicated test account on your own application with synthetic data.
Google, Microsoft and sites requiring MFA stay human: omit `sign_in` for them.
Add this optional declaration to the site's existing object:

```json
"sign_in": {
  "mode": "automatic",
  "url": "https://shop.example.com/login",
  "steps": [
    {"fill": "#email", "secret": "email"},
    {"fill": "#password", "secret": "password"},
    {"click": "button[type=submit]"}
  ]
}
```

The URL must have the site's origin. Fill steps refuse to type after a redirect
to another origin. Selectors and field names are nonsecret; never put values in
settings. Store each field once on the machine that runs the Browser case:

```text
yoke projects capability secret set --project P --cap-type browser-control --key sign-in.buyer.shop.email --value-file /private/path/test-email
yoke projects capability secret set --project P --cap-type browser-control --key sign-in.buyer.shop.password --value-stdin
```

Enter the value privately through stdin or a file; agents must never read it or
put it in a command argument. The fixed key pattern is
`sign-in.IDENTITY.SITE.FIELD`, with 1–40 lowercase letters, digits or hyphens
per name. Values live only under this machine's
`~/.yoke/secrets/capability-secrets/P/browser-control/`, beside its profiles;
they are never sent to the control plane. Configure every runner machine once.

`authorize` signs expired automatic sites in without opening a window. Before
starting its daemon, a Browser case stops its identity's daemon, checks the
sites, signs expired automatic sites in, and verifies the result. `verify` stays
read-only. The managed Playwright browser uses its existing basic password
store and mock Keychain switches, including headless background execution;
it needs no GUI login session or macOS Keychain approval. Sign-in has no
screenshots or tracing, and reports site states without page text or raw errors.
Native Test Machine browser sign-in remains human.

A Browser case can also sign in during its run after sign-out or session
expiry: use `{"action": "sign_in", "site": "shop"}` with this identity selected.
It uses the daemon's open context and the case's page, then checks the site's
signed-in probe. The step result records only the site, identity and check
outcome. Python passes secret file paths to the daemon; only the sign-in
function reads their values. Never put credentials in authored step values.
A site without automatic `sign_in` refuses as
`browser_sign_in_step_not_automatic`; declare it for that identity or keep
human sign-in outside the case.

`browser_sign_in_secret_missing` names the exact secret setup command.
`browser_automatic_sign_in_failed` names the site: check the account and steps,
then retry, or remove `sign_in` and run `yoke browser authorize` for human
sign-in. A failed automatic sign-in stops the case before it captures anything.

## Signing in on a Test Machine

Run from the workstation connected to the project's control plane:

```text
yoke browser authorize --project P --identity buyer --test-machine NAME
```

Yoke reads the browser-control declarations here and runs authorization in the
registered Test Machine's GUI session over its SSH route. A Linux or Windows
WSL machine with a registered RDP desktop opens in the same FreeRDP viewer as
`yoke test-machine desktop-access --view` (fixture password on stdin, SSH
forward closed with the viewer). A window titled `Yoke desktop: NAME` appears.
Sign in with the identity's declared account. Close the browser window when
done; the viewer closes when verification finishes. If no viewer route or
FreeRDP client is available, the command prints the exact `desktop-access`
command and recovery and still waits for sign-in. macOS Screen Sharing uses
that printed command without `--view`. The Test Machine needs an installed
Yoke browser runtime, but no control-plane connection or pasted settings.
Read `yoke browser authorize --help` for reset, starting URL, JSON output
and window bounds.

On Linux and macOS, `--test-machine NAME` checks both automation and native desktop
browser sign-ins. Add `--desktop-browser` to check only that machine's native
Chromium or Safari. Native sign-ins stay live through resets and are never saved
into golden snapshots or wiped by authorization. A second Linux viewer refuses
`linux_desktop_viewer_connected`; close the open `Yoke desktop: NAME` viewer or
let its authorization finish, then retry. Linux authorization uses `xdotool`
to detect closure of the spawned Chromium PID's windows before verification.
If an approval walk finds a Google or Microsoft sign-in page instead of its exact
request tab, it names `machine_browser_sign_in_required`. The operator completes
the declared identity's native sign-in before retrying; approval automation never
enters credentials or clicks an unrelated request.

The workstation needs an ssh-agent with a key the host accepts. macOS uses its
logged-in Terminal.app session; Linux and Windows WSL use the registered user's
XFCE desktop. For a desktop that needs to start, its registered `desktop_password`
secret must be stored on this workstation. A machine leased by another session
refuses: wait for that lease to release or ask its holder to authorize the
identity, because signing in stops every automated browser on that host.
Read [desktop access](test-machine-desktop.md) for the viewer route,
FreeRDP client and macOS Screen Sharing recovery.

## Using an identity

`yoke qa browser setup|status|stop|screenshot|step` take `--identity NAME`
and read no declarations, so they run on a host that cannot reach the
project's control plane. `verify` and `authorize` need the identity's sites:
for a registered Test Machine, authorize from the connected workstation with
`--test-machine NAME`. For hosts without a remote route, run locally there with
`--declarations-json`, using the browser-control settings document read where
the project is reachable. `--test-machine` and `--declarations-json` are exclusive. A
Browser case that needs sign-in names its identity with
`method_config.browser_identity`. Choose the identity whose account can access
the case's routes and data; an account signed into a different organization
cannot prove a case about your organization. The runner validates named identities
before starting any browser daemon. Public cases omit the field and continue
on the `default` daemon without requiring a sign-in identity, even when the
project declares named identities. Only identities with automatic sites run a
pre-case sign-in check; human sites keep their existing behavior. The runner
can also select a recorded account if navigation reaches its account chooser.
`authorize` and `verify` still refuse a missing `--identity` when `default`
has no sites and another identity does. A run whose cases name several identities starts
one daemon per identity. An
exploratory mission can select personas with `method_config.browser_identities`,
for example `["operator"]`; this list wins. With no list, dispatch supplies all
project-declared identities whose sites cover the target base URL origin,
including their site checks and accounts through the declarations. The walker
chooses the account the case needs. An uncovered target supplies no identities.
Any mission with selected identities
uses the managed browser even when it installs nothing; host-browser access
is reserved for missions naming none that have not installed Yoke.
The dispatch gives the walker an exact
`yoke browser verify` per identity to run before browsing. For an expired site,
the walker runs `yoke browser authorize` on that host and re-signs in itself,
or routes an approval to steering. Only a password or credential entry the
agent may not type returns `WALK_STATUS: HUMAN_GATE`, naming that one entry,
the identity, site, account and resume state.

## Identities on test machines

Sites rotate session cookies, so a sealed copy of a signed-in profile is stale
by the time it is restored. A test machine therefore keeps its identities live
in `~/.yoke-browser-identities`, outside `~/.yoke`. A full reset keeps that
store the way it keeps harness logins, and golden capture never includes it,
while `~/.yoke` itself is still absent after the reset. Once the walk installs
Yoke, each identity's profile path links into the store, so the product reads
and refreshes the live sessions in place and nothing is saved or restored.
Create the store once during host provisioning, owner-only (`mkdir -m 700
~/.yoke-browser-identities`). A profile already signed in at its
capability-secrets path is moved into the store the first time it is resolved.
The Machine QA per-OS procedures at `.yoke/docs/verification/test-machines/browser-identities.md`
(installed by the Machine QA) cover desktop preparation and the first sign-in.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
