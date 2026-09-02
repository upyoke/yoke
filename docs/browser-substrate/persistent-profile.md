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

`<project>` is the project reference, filesystem-normalized. Every caller —
`yoke browser authorize` and each daemon-start path — resolves it through
`browser_profile.profile_project_key`, so the profile the operator signs into
is the profile a worker later opens. Omitting `--project` resolves the
checkout you are standing in, which is the recommended default.

## Signing in

```sh
yoke browser authorize                        # this checkout's project
yoke browser authorize --project yoke
yoke browser authorize --url https://app.upyoke.com
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
resolved through `chromium.executablePath()`. The profile's cookies are
encrypted against that binary's OS keychain entry, so a profile signed in with
the daemon's Chromium is readable by the daemon afterwards, while one signed in
with Google Chrome or Safari writes cookies the daemon cannot decrypt.

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

Check what a run here would open:

```sh
yoke qa browser status --project yoke
```

## Expiry

Expiry needs no machinery. A dead session lands the walker on a sign-in page,
which is already the human gate it raises. Run `yoke browser authorize` again
for that site.
