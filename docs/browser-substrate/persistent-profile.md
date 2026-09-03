# Persistent Browser Profile

An agent must never complete a sign-in. So the signed-in state a Browser case
or an exploratory walker needs comes from the operator, once, in a browser
window they drive themselves — and every worker context the daemon hands out
afterwards inherits it.

Without this, every context the daemon opened started with an empty cookie
jar, and any criterion rendered behind a dashboard sign-in stayed
`NOT_TESTABLE` no matter how the case was written.

## Where the profile lives

One profile directory per project, beside that project's other machine-local
capability secrets:

```text
~/.yoke/secrets/capability-secrets/<project>/browser-control/profile
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
yoke browser authorize                        # this checkout's project
yoke browser authorize --project yoke
yoke browser authorize --url https://app.upyoke.com
yoke browser authorize --reset                # start from an empty profile
```

The command opens the profile in a plain window of the daemon's own Chromium
and waits until you close it. Sign into as many sites as you like; whatever the
window ends up holding is what the project's Browser cases and walkers get.
There are no origin lists, no declarations, no per-site probes, and no exported
storage state.

### Why the window is plain, and why it is that binary

The window is a directly spawned browser process — `--user-data-dir` on the
profile, plus the first-run and default-browser prompts turned off — and never
a Playwright context. Playwright's `launchPersistentContext` runs the browser
under automation control: `--enable-automation`, `navigator.webdriver`, an
attached debugging session. Google's sign-in refuses exactly that shape with
"Couldn't sign you in. This browser or app may not be secure", listing browsers
"being controlled through software automation rather than a human" among what
it will not accept. So a profile opened through Playwright could not be signed
into through Google at all, which is the sign-in most operators need. The fix
is to stop presenting as automation, not to mask the signals; hiding
`navigator.webdriver` is a losing arms race against a published policy.

It has to be the same binary the daemon drives — Playwright's own Chromium,
resolved through `chromium.executablePath()` — launched with the same
cookie-encryption switches. Chromium encrypts every stored cookie against a key
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
yoke browser authorize --reset
```

Stops the daemon, deletes this project's profile directory, and opens a fresh
window. Everything the profile was signed into is gone. Use it for a profile
signed into the wrong account, a sign-in that will not take, or a damaged
cookie store — the refusal from a damaged store names this command. The
directory to delete is resolved from the project reference rather than accepted
from the caller, so the only profile the command can remove is the one named.

Chromium locks a profile directory and the daemon is a machine singleton, so
`authorize` stops a running daemon first. The next case run starts it again on
the profile you just signed into.

## How a run uses it

`daemon_start(profile_dir=...)` launches Playwright's persistent context on
that directory instead of a throwaway browser. A daemon already running on a
*different* profile is stopped and restarted rather than reused — reusing it
would hand this project's workers another project's signed-in session. The
daemon records the directory as `profileDir` in
`~/.yoke/browser-runtime/.daemon-state.json`, which is how that comparison is
made.

A project with no profile is not a refusal: it gets a clean throwaway context,
exactly as before profiles existed. The startup log still names the situation,
and when *other* projects do have profiles it lists their references — a
profile signed in under one reference and looked for under another is
otherwise a silent miss.

`--project` takes the same reference, with the same checkout default, on
`yoke qa browser screenshot`, `yoke qa browser step`, `yoke qa browser setup`,
and `yoke qa browser status`. Check what a run here would open:

```sh
yoke qa browser status --project yoke
```

A reference that cannot be resolved to a slug is a refusal, not a silent clean
context: the daemon-start paths return the named reason and the recovery
(`yoke env list`, or name the project by slug), and `status` reports it as the
profile facet.

## Expiry

Expiry needs no machinery. A dead session — the site's own expiry, or the
30-day lifetime given to a kept session cookie — lands the walker on a sign-in
page, which is already the human gate it raises. Run `yoke browser authorize`
again for that site.
