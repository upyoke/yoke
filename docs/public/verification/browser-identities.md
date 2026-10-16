# Browser sign-in identities

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Browser identities
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
that HTTP status).

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
runs the same check first and returns at once when every site is signed in.
Otherwise it opens one window with a tab per expired site, naming the identity,
the site and the account, and checks again after the window closes. A site
whose check cannot be reached fails by name: no sign-in fixes it.

While a sign-in window is open no automated browser runs on the machine: every
browser daemon is stopped first, and a daemon start is refused with
`browser_human_gate_active` until the window closes.

## Signing in on a Test Machine

Run from the workstation connected to the project's control plane:

```text
yoke browser authorize --project P --identity buyer --machine NAME
```

Yoke reads the browser-control declarations here and runs authorization in the
registered Test Machine's GUI session over its SSH route. Sign in on that
desktop, then close the browser window; the command checks the identity again
there before returning. The Test Machine needs an installed Yoke browser runtime,
but no control-plane connection or pasted settings. Read `yoke browser authorize
--help` for reset, starting URL, JSON output and window bounds.

The workstation needs an ssh-agent with a key the host accepts. macOS uses its
logged-in Terminal.app session; Linux and Windows WSL use the registered user's
XFCE desktop. For a desktop that needs to start, its registered `desktop_password`
secret must be stored on this workstation. A machine leased by another session
refuses: wait for that lease to release or ask its holder to authorize the
identity, because signing in stops every automated browser on that host.
Use [desktop access](test-machine-desktop.md) to view the remote desktop.

## Using an identity

`yoke qa browser setup|status|stop|screenshot|step` take `--identity NAME`
and read no declarations, so they run on a host that cannot reach the
project's control plane. `verify` and `authorize` need the identity's sites:
for a registered Test Machine, authorize from the connected workstation with
`--machine NAME`. For hosts without a remote route, run locally there with
`--declarations-json`, using the browser-control settings document read where
the project is reachable. `--machine` and `--declarations-json` are exclusive. A
Browser case names its identity with `method_config.browser_identity`; a run
whose cases name several identities starts one daemon per identity. An
exploratory mission can select personas with `method_config.browser_identities`,
for example `["operator"]`; this list wins. With no list, dispatch supplies all
project-declared identities whose sites cover the target base URL origin,
including their site checks and accounts through the declarations. The walker
chooses the account the case needs. An uncovered target supplies no identities.
Any mission with selected identities
uses the managed browser even when it installs nothing; host-browser access
is reserved for missions naming none that have not installed Yoke.
The dispatch gives the walker an exact
`yoke browser verify` per identity to run before browsing, and an expired site
is a human gate naming the identity, site and account.

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
The Machine QA Pack per-OS procedures at `docs/packs/machine-qa/browser-identities.md`
(installed by the Machine QA Pack) cover desktop preparation and the first sign-in.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
