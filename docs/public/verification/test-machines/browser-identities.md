# Browser identities on test machines

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Machine browser identities
<!-- /yoke:breadcrumbs -->

A browser identity is one persona's whole browser profile, signed into every
site that persona uses. A project declares its identities, each with a
signed-in check per site, in its `browser-control` capability settings; the
product reference `.yoke/docs/verification/browser-identities.md`
owns the declaration shape and the `yoke browser verify` and `yoke browser
authorize --identity NAME` commands.

A test machine keeps identities live in `~/.yoke-browser-identities`, outside
`~/.yoke`. The full reset keeps that store the way it keeps harness logins and
golden capture never includes it, because sites rotate session cookies and a
restored copy of a session is stale. Nothing is sealed or restored: the first
authorization creates the store and every profile lives in it, so sessions the
site refreshes during a walk persist. Setup and first sign-in live in the
complete per-OS procedures:

- [Linux, step 5](linux-browser-identities.md)
- [macOS sign-in procedure](#macos-sign-in-procedure)
- [Windows/WSL2, step 6](windows-browser-identities.md)

Agents do every step that does not need the user; personal credentials are
entered by the user, and only for the sites the check reports expired. Profile
data stays on the host. Use the saved human session for native harness login.
Tests use agent captures; human viewing serves only a requested, announced
personal sign-in handoff, never a test acceptance check.

## Machine sign-in and approval

On macOS, Linux and WSL a test machine's identity profiles are its only saved
login store; no stock desktop browser holds a sign-in. Sign each
identity in from the connected workstation:

```text
yoke browser authorize --project PROJECT --identity IDENTITY --test-machine NAME
```

Declare that identity's sites, signed-in probes and account names in
`browser-control` first. It opens tabs only for expired sites and names the
account to use. Unreachable probes refuse before tabs open: repair the named
network condition, then retry. Remote `--reset` resets only that identity.
Require release-matched help and operation receipts before relying on
installed support. Real-host sign-in and reset proof remain separate from
merged source and CI evidence.

Every person-facing page on the machine opens in an identity profile with
`yoke browser open --project P --identity NAME URL`: the same Chromium binary
and flags `authorize` uses, plus a loopback DevTools port. When that
profile's browser is already running, the URL opens as a new tab there. An
unauthorized identity refuses with `browser_identity_not_authorized`, naming
the `authorize --test-machine` command. It needs no control-plane connection.
Desktop missions without named identities open pages this way with the
project's `default_identity` through the lease host command, never the stock
desktop browser.

The machine's operator identity is the project's browser-control
`default_identity`. A recipe step typed `operator_gate:
machine_browser_approval` exports, before its entry command:

```text
BROWSER="env -u YOKE_MACHINE_HOME <yoke_bin> browser open --project P --identity <operator identity> %s"
```

The installer's link opener honors the standard `BROWSER` variable on every
platform: it tries each `os.pathsep`-separated command, replacing `%s` with
the URL or appending it. So the installer's **Approve machine** link opens in
the operator identity's signed-in browser. A project without
`default_identity` blocks the recipe with
`machine_operator_identity_undeclared`, naming `yoke projects
capability-settings merge --project P --cap-type browser-control --set
default_identity=NAME`.

One approval driver serves Linux, WSL and macOS. It runs the test machine's
installed Yoke over SSH (`yoke browser devtools tabs` and `approve`, an
internal command), so the host needs no other interpreter. That Yoke reads
every `~/.yoke-browser-identities/*/*/DevToolsActivePort`, finds the exact
approval tab and presses **Approve machine**. When that command returns no
readable receipt, the gate refuses with reason
`identity_browser_helper_unreadable`, naming the installed Yoke path. A tab that landed on a sign-in page means the login expired: it
refuses `machine_browser_sign_in_required`, whose recovery names the exact
`yoke browser authorize --project P --identity NAME --test-machine T`
command. Nobody signs in inside that window. When no identity browser runs,
it refuses `machine_browser_tab_missing`: the installer did not open its
link through `yoke browser open`.

Before a capture or reset, Linux and WSL ask every Chromium to quit and never
kill it. macOS finds each identity browser's main process with `/bin/ps`,
sends it SIGTERM (Chromium's clean shutdown, which saves its cookies) and
waits up to 30 seconds; it never force-quits. A browser still running refuses
`test_machine_sign_in_app_quit_not_proved`: close its windows and retry. A
failed process probe refuses `test_machine_sign_in_app_probe_failed`: check
SSH and retry.

Native Windows follows the same route in PowerShell; see
[native Windows browser identities](windows-browser-identities.md). Stock
Safari, Edge and snap Chromium are no longer exercised, and the installer's
handoff to the OS default browser is not exercised on any test machine.

## macOS sign-in procedure

A test machine keeps each project identity signed in live, outside the
clean-home golden.

1. The first authorization creates the live identity store
   `~/.yoke-browser-identities` owner-only, outside `~/.yoke`. A full reset
   keeps it the way it keeps harness logins, and golden capture never includes
   it, because a restored copy of a session is the cookies the site has since
   rotated. Never create or move it by hand.
2. Agents use the registered test user and leased product operations to install
   the candidate and prepare its Chromium runtime and real headed desktop.
   Declare the project's identities and each identity's per-site sign-in
   checks in its `browser-control` capability settings; see
   the installed declaration reference
   `.yoke/docs/verification/browser-identities.md`.
3. For each identity, agents run `yoke browser authorize --project P
   --identity NAME` as the test user in the real headed desktop; read
   `--help`. It checks every declared site first and opens a window only for
   the expired ones, naming the identity, the site and the account; no
   automated browser runs while it is open. The user only types their own
   password or credential; agents drive every other prompt in that window
   through desktop control, prepare the desktop and run the declared checks; use project-approved test accounts
   and follow project-owned sign-in policy. Keep profile data on the host.
4. Agents close each authorization window once signed in; the command checks each site
   again and fails naming any still signed out. The identity's profile
   is saved in the store, so the sign-in already lives there: nothing is
   captured, sealed or restored.
5. A reset removes `~/.yoke` and keeps the store. Once a walk installs the
   candidate, `yoke browser verify --project P --identity NAME` proves each
   site still signed in, and sessions a site refreshes during the walk persist
   in the store whether the walk passes, fails or is aborted.
6. For an expired site, agents run `yoke browser authorize --identity NAME`
   on that host and re-sign in themselves, or route an approval to steering.
   Only password or credential entry the agent may not type is a `HUMAN_GATE`,
   naming that one entry, machine, identity, site, account and resume state.
   Runtime and inventory failures retain their named diagnostics.

Use the logged-in, unlocked test-user desktop through Screen Sharing and the
GUI Terminal context; the login keychain remains that user's.

Return to [macOS host provisioning](macos-baseline-recovery.md#11-live-browser-identities).

## macOS automation diagnostics

`-25211` names Device Control and Data Access (Accessibility on older macOS).
A GUI-session command that names Terminal needs Terminal's separate grant,
even when the Remote Login helper is already enabled. Approve Terminal on
the unlocked test desktop, run the same GUI operation, and confirm the
expected result of the input. A command that exits successfully can still
leave the target unchanged. `-1743` names Automation. Repair the named grant
in the UI for the failing controller and rerun. Diagnosis and each Terminal case probe
Terminal → System Events: `terminal_system_events_automation_missing` means
`-1743`, `terminal_system_events_automation_timeout` means timeout without
denial, and `terminal_window_accumulation` means timeout with over 10 windows
(reset quits them). Diagnosis names the visible window count and refuses
`terminal_window_close_failed` if its own window remains. Disconnect an active
Screen Sharing curtain or reconnect without curtain. Home restore cannot
recreate these grants.
