# Linux browser identities

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Verification](../index.md) > [Machine QA](index.md) > Linux browser identities
<!-- /yoke:breadcrumbs -->

Return to [Linux host provisioning](linux-host-provisioning.md).

Required authorization behavior:

Run yoke browser authorize to check automation identities and Test Machine
desktop browser sign-ins. It opens tabs only for expired sites and names the
account to use. Desktop browser sign-ins stay live through reset and are
excluded from golden snapshots.

The remote `--test-machine NAME` command includes both checks by default; there
is no desktop opt-out. Confirm release-matched help and operation receipts
before relying on an installed release. Before running it, read the complete
[desktop browser checks](browser-identities.md#desktop-browser-checks) procedure.

A test machine keeps each project identity signed in live, outside the
clean-home golden.

1. As the test user, create the live identity store once:
   `mkdir -m 700 ~/.yoke-browser-identities`. Never place it inside `~/.yoke`.
   A full reset keeps it the way it keeps harness logins, and golden capture
   never includes it, because a restored copy of a session is the cookies the
   site has since rotated.
2. Agents use the registered test user and leased product operations to install
   the candidate and prepare its Chromium runtime and real headed desktop.
   Declare the project's identities and each identity's per-site sign-in
   checks in its `browser-control` capability settings; see
   [browser identities](browser-identities.md).
3. For each identity, agents run `yoke browser authorize --project P
   --identity NAME` as the test user in the real headed desktop; read
   `--help`. It checks every declared site first and opens a window only for
   the expired ones, naming the identity, the site and the account; no
   automated browser runs while it is open. The user only types their own
   password or credential; agents drive every other prompt in that window
   through desktop control, prepare the desktop and run the declared checks; use project-approved test accounts
   and follow project-owned sign-in policy. Keep profile data on the host.
4. Agents close each authorization window once signed in; the command checks each site
   again and fails naming any still signed out. The identity's profile path
   links into the store, so the sign-in already lives there: nothing is
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

The real headed session comes from the registered XFCE desktop route in
step 4, never a dummy display.

### Browser approval gates

A recipe step with `operator_gate: machine_browser_approval` approves the
installer's one-time code in this desktop's Chromium, under the same contract
as Safari on macOS. The gate requires `/usr/bin/x-www-browser` to resolve to
a Chromium program, the browser desktop links open, and starts it with a login shell's
`XDG_DATA_DIRS` so it matches the desktop session. Before
the installer starts, the gate starts or reuses the fixture desktop and Chromium
with a loopback-only DevTools port, restarting a running Chromium gracefully
when it lacks one; the installer's tmux session carries the desktop's DISPLAY,
so its approval link opens there. The gate then
presses **Approve machine** only in the exact installer-opened tab on the
declared origin with the displayed code, revalidates the tab first, accepts
only a same-origin navigation away from it, and attaches a desktop screenshot
to the step. Agents open the app sign-in once in this Chromium; the operator
types only their password. Keep
that browser sign-in live outside the golden and prove it survives reset
through the [baseline procedure](linux-baseline-recovery.md); golden capture
saves the remaining fixture state, never the desktop browser sign-in store.

While the gate's Chromium runs, any process of a local user can reach its
loopback DevTools port, so keep the host dedicated to the fixture user.

| Refusal | Recovery |
| --- | --- |
| `headless_linux_browser_approval_unavailable` | The host has no usable desktop: provision step 4 and store `desktop_password` |
| `linux_desktop_default_browser_not_chromium` / `linux_desktop_chromium_missing` | Rerun the step 4 provisioner |
| `linux_desktop_session_environment_unavailable` | Install bash so a login shell can print `XDG_DATA_DIRS` (`bash -lc`), then rerun |
| `linux_desktop_chromium_devtools_unavailable` | Close Chromium on the desktop and rerun; use the provisioned Chromium snap |
| `linux_desktop_chromium_quit_not_proved` | Close every Chromium window, answering its prompts, then rerun; it is never force-killed |
