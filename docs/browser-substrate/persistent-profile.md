# Persistent Browser Profile

An agent must never complete a sign-in. So the signed-in state a Browser case
or an exploratory walker needs comes from the operator, once, in a browser
window they drive themselves — and every worker context the daemon hands out
afterwards inherits it.

Without this, every context the daemon opened started with an empty cookie
jar, and any criterion rendered behind a dashboard sign-in stayed
`NOT_TESTABLE` no matter how the case was written.

## Where the profile lives

One profile directory per project **identity**, beside that project's other
machine-local capability secrets. An identity is one persona's whole profile
— every site that persona uses, signed in together. A project declares named
identities in its `browser-control` capability settings
(`yoke_contracts.browser_identity`); `default` always exists and keeps the
project's original single-profile path, so a project that declares nothing
behaves as before and a profile signed in before identities existed is the
`default` identity's profile:

```text
~/.yoke/secrets/capability-secrets/<project>/browser-control/profile                     # default
~/.yoke/secrets/capability-secrets/<project>/browser-control/identities/<name>/profile   # every other identity
```

It is a Chromium profile holding live session cookies, so it is owner-only
(`0700`, including every parent up to the secrets root) and never reaches the
database, the repository, QA artifacts, or a transcript. The path contract is
`yoke_contracts.machine_config.capability_secrets.browser_profile_relative_path`;
`yoke_cli.config.browser_profile` resolves, creates, and reports it.

`<project>` is the project **slug**, filesystem-normalized. Every caller —
`yoke browser authorize` and each daemon-start path — resolves it through
`browser_profile.profile_project_key`, so the profile the operator signs into
is the profile a worker later opens. Omitting `--project` resolves the
checkout you are standing in, which is the recommended default.

The slug is what makes those two agree. The two sides are handed different
references for the same project: `--project yoke` is the slug an operator
typed, while the checkout default answers with the numeric project id. Keyed by
whatever each was handed, they named two directories for one project — a run
started from the checkout opened a clean context and captured the signed-out
page while the operator's signed-in profile sat under the other key. So an
id-shaped reference is resolved to its slug (through the registered
`projects.get` read) before it names a directory, and a slug is already
canonical. Nothing migrates a directory left under a pre-slug key: delete it
and run `yoke browser authorize` again.

## Signing in

```sh
yoke browser verify --identity admin              # admin: google ok, yoke expired
yoke browser authorize --identity admin           # window only for expired sites
yoke browser authorize                            # default identity, this checkout
yoke browser authorize --identity admin --reset   # start that identity from empty
```

Each site an identity declares carries its own signed-in check: a URL plus a
selector only a signed-in page shows (the page must also show no sign-in wall,
the same detection a case step uses), or the HTTP status a signed-in request
answers without following redirects. `verify` runs every check headless on the
identity's profile and reports each site. `authorize` runs the same checks
first: when every site is signed in it returns without a window. Otherwise it
opens the profile in a plain window of the daemon's own Chromium, one tab per
expired site, naming the identity, the site and the account to use, waits until
you close every authorization window, and checks again — a site still signed
out fails by name. A site whose check gets no answer fails without a window,
because no sign-in fixes it. An identity that declares no sites has nothing to
check, so the window opens as it always did. Nothing is exported: whatever the
window ends up holding is what that identity's Browser cases and walkers get.

No automated browser runs while a human signs in. Before the window opens,
every browser daemon on the machine is stopped (any project, any profile) and a
machine-wide marker (`human-sign-in.json` in the runtime directory) is held
until the window closes; a daemon start meanwhile is refused with
`browser_human_gate_active`, naming the identity being signed in. An automated
window left on screen is the window a person signs into by mistake, and
identity providers refuse a browser they can see is automated.

On macOS, closing the last window can leave Chromium running with no window.
The command counts windows owned by the browser process it spawned, including
minimized windows, then asks that process to shut down when the last one closes.
It waits for Chromium to exit before updating session cookies or reporting the
profile saved, so the daemon can open the profile without its lock. A browser
that opens no window within 30 seconds, or stays running for 30 minutes, is
stopped with a named condition. If it still holds the profile after 10 seconds,
the error names its PID: quit that process normally and rerun the command
without `--reset`. The profile directory is never discarded by this recovery.

### Why the window is plain, and why it is that binary

The window is a directly spawned browser process — `--user-data-dir` on the
profile, plus the first-run and default-browser prompts and background mode
turned off — and never
a Playwright context. Playwright's `launchPersistentContext` runs the browser
under automation control: `--enable-automation`, `navigator.webdriver`, an
attached debugging session. Google's sign-in refuses exactly that shape with
"Couldn't sign you in. This browser or app may not be secure", listing browsers
"being controlled through software automation rather than a human" among what
it will not accept. So a profile opened through Playwright could not be signed
into through Google at all, which is the sign-in most operators need. The fix
is to stop presenting as automation, not to mask the signals; hiding
`navigator.webdriver` is a losing arms race against a published policy.

Authorization and the daemon use the same resolved browser: the verified
system executable selected by setup, or bundled Chromium from
`chromium.executablePath()`. Both use the same cookie-encryption switches. Chromium encrypts every stored cookie against a key
it takes from the platform credential store, and silently drops any cookie it
cannot decrypt when it loads the profile. Playwright always launches with
`--password-store=basic --use-mock-keychain`, which is a different key domain
from a default browser launch, so a window opened without them wrote a whole
sign-in the daemon then threw away. `buildLaunchArgs` passes the same two
switches, and the authorize tests assert both that the window carries them and
that Playwright's own launch still does. A profile signed in with Google Chrome
or Safari is unreadable for the same reason, and cannot be fixed by a switch.

One consequence is worth naming: on macOS those switches mean the profile's
cookies are encrypted with a fixed key rather than a Keychain-derived one. What
protects them is the same thing that protects the rest of the directory — it is
owner-only, `0700`, under the machine's capability secrets. The alternative,
stripping the switches from the daemon instead, would put an automated
background browser in front of a credential-store prompt on macOS and a
`gnome-keyring`/`kwallet` prompt on a self-hosted Linux box, which is how an
unattended run hangs instead of failing.

## How the sign-in survives the window closing

A site that authenticates with a session cookie — no `Max-Age`, no `Expires` —
sets a cookie an ordinary browser drops when it quits. Chromium restores such
cookies only for a profile continuing its previous session, which an automated
launch never is. So the operator's sign-in evaporated the moment they closed
the window: the profile was authorized, the daemon opened it, and every page
rendered signed out with an empty cookie store.

Chromium offers no switch that changes this for the daemon's launch. Both
candidates were measured against a real Playwright persistent context and
neither preserved a session cookie: the profile preference that means "continue
where you left off" (`session.restore_on_startup = 1`, written into
`Default/Preferences` before launch, and still present in the file afterwards),
and the `--restore-last-session` command-line switch. What a persistent context
does keep is a cookie the store already considers persistent.

So between the window closing and the next context opening, every session
cookie in the profile is given an explicit expiry —
`SIGN_IN_COOKIE_LIFETIME_DAYS` in `yoke_cli.config.browser_profile_cookies`,
30 days. The encrypted value is never touched, only the row's lifetime. This
runs at both moments where no browser holds the profile: when `yoke browser
authorize` returns, which reports the count, and before `daemon_start` launches
a persistent context, which also carries forward any session cookie the site
refreshed during the previous run. A cookie store that cannot be updated is
named in the daemon log and the run proceeds signed out — the same outcome an
unauthorized project already gets — rather than failing the run.

This is a deliberate extension of a lifetime the site chose, which is the whole
purpose of an authorized profile: it exists to hold one operator sign-in for
later automated runs. It is bounded rather than indefinite for that reason.

## Starting over

```sh
yoke browser authorize --identity admin --reset
```

Deletes that identity's profile and opens a fresh window for every site it
declares. Everything that identity was signed into is gone; other identities
are untouched. Use it for a profile
signed into the wrong account, a sign-in that will not take, or a damaged
cookie store — the refusal from a damaged store names this command. The
directory to delete is resolved from the project reference rather than accepted
from the caller, so the only profile the command can remove is the one named.

`verify` needs the profile free (Chromium locks a profile directory), so it
stops only the daemon serving that identity; the next case starts it again.

## How a run uses it

`daemon_start(profile_dir=...)` launches Playwright's persistent context on
that directory. Each canonical profile path owns one daemon, reused by all
workers for that profile. Its state and log live under
`~/.yoke/browser-runtime/daemons/<sha256-of-profile-path>/`; the separate
`throwaway` key serves callers with no authorized profile. The OS assigns
an available port, and the state file publishes the actual endpoint.

A QA capture binds all requests, health checks and owned pages to its profile.
Starting, stopping or idling out another profile's daemon never touches it.
Same-profile cases use distinct owned pages and share cookies by design;
different profiles have separate browser contexts and cookie jars. Startup
retries stop only a verifiably unhealthy daemon for the requested profile,
and preserve a healthy daemon even after a transient startup failure.

A project with no profile is not a refusal: it gets a clean throwaway context,
exactly as before profiles existed. The startup log still names the situation,
and when *other* projects do have profiles it lists their references — a
profile signed in under one reference and looked for under another is
otherwise a silent miss.

`--project` takes the same reference, with the same checkout default, and
`--identity NAME` selects the identity, on `yoke qa browser screenshot`,
`step`, `setup`, `status` and `stop`. Starting a daemon reads no
declarations, so a host that cannot reach the project's control plane still
runs; an identity never signed in there gets a clean context, named in the
log with the command that signs it in. `verify` and `authorize` need the
identity's sites: on such a host pass the project's browser-control settings
document with `--declarations-json`, read where the project is reachable.
A Browser case names its identity with `method_config.browser_identity`;
a run whose cases name several starts one daemon per identity. Check what a run
here would open:

```sh
yoke qa browser status --project yoke --identity admin
```

A reference that cannot be resolved to a slug is a refusal, not a silent clean
context: the daemon-start paths return the named reason and the recovery
(`yoke env list`, or name the project by slug), and `status` reports it as the
profile facet.

## Expiry

`yoke browser verify` finds an expired session before anything browses, and
`yoke browser authorize --identity NAME` asks a human only for the sites it
reports expired. An exploratory mission lists the identities it needs in
`method_config.browser_identities`, and its walker runs the exact verify
command for each before browsing; an expired site is the human gate, naming
the identity, site and account. A Browser QA case that still lands on a sign-in
page records `sign_in.authenticated` as false with its identity, and a
wait_for or assert timeout there is `execution_target_unauthorized` naming
`yoke browser authorize --identity NAME` rather than a missing selector.

## Identities on test machines

Sites rotate session cookies, so a sealed copy of a signed-in profile is stale
by the time it is restored. A test machine keeps its identities live in
`~/.yoke-browser-identities/<project>/<identity>/`
(`LIVE_IDENTITY_STORE_HOME_ENTRY`), outside `~/.yoke`. The macOS and Linux full
resets keep that store exactly as they keep live harness logins, and golden
capture never includes it, while `~/.yoke` is still absent after a reset. When
the store exists, `yoke_cli.config.browser_profile` makes each identity's
capability-secrets path a link into it, so the installed product reads and
refreshes the live sessions in place — a walk that fails or is aborted keeps
whatever the site refreshed. A real profile found at the capability path when
the store has none for that identity is moved into the store, never discarded;
a profile in both places refuses with `browser_identity_store_conflict`.
