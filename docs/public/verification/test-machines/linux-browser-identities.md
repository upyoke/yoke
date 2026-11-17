# Linux browser identities

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Linux browser identities
<!-- /yoke:breadcrumbs -->

Return to [Linux host provisioning](linux-host-provisioning.md).

Run `yoke browser authorize --test-machine NAME` to check each identity. It
opens tabs only for expired sites and names the account to use. The identity
profiles are the machine's only saved login store; there is no separate
desktop browser sign-in. Confirm release-matched help and operation receipts
before relying on an installed release. Before running it, read the complete
[machine sign-in](browser-identities.md#machine-sign-in-and-approval) procedure.

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

The real headed session comes from the registered XFCE desktop route in
step 4, never a dummy display.

### Browser approval gates

A recipe step with `operator_gate: machine_browser_approval` approves the
installer's one-time code in the operator identity's browser, under the same
contract as macOS and WSL. The operator identity is the project's
browser-control `default_identity`. Before the entry command the recipe
exports `BROWSER` as `yoke browser open` for that identity, and the
installer's tmux session carries the desktop's DISPLAY, so the installer's
**Approve machine** link opens signed in on this desktop. Desktop links
(`xdg-open`) land in the same profile through the
[identity launcher](linux-host-provisioning.md#4-durable-desktop-and-unattended-sessions) provisioning registers.

The gate starts or reuses the fixture desktop before the installer starts.
It then runs the machine's installed Yoke over SSH (`yoke browser devtools`),
which finds the exact installer-opened tab through each identity browser's
loopback DevTools port, on the declared origin with the displayed code. It presses **Approve
machine** only there, revalidates the tab first, accepts only a same-origin
navigation away from it, and attaches a desktop screenshot to the step. The
first sign-in happens once with `yoke browser authorize --test-machine`;
the store survives reset through the
[baseline procedure](linux-baseline-recovery.md) and golden capture never
includes it.

While an identity browser runs, any process of a local user can reach its
loopback DevTools port, so keep the host dedicated to the fixture user.
Before a capture or reset, Yoke asks every Chromium to quit and never kills
it.

| Refusal | Recovery |
| --- | --- |
| `machine_operator_identity_undeclared` | Set the operator identity: `yoke projects capability-settings merge --project P --cap-type browser-control --set default_identity=NAME` |
| `headless_linux_browser_approval_unavailable` | The host has no usable desktop: provision step 4 and store `desktop_password` |
| `machine_browser_sign_in_required` | The identity's login expired: rerun the named `yoke browser authorize --project P --identity NAME --test-machine T`; nobody signs in inside that window |
| `machine_browser_tab_missing` | No identity browser runs: the installer did not open its link through `yoke browser open`; check the recipe's `BROWSER` export |
| `linux_desktop_default_browser_not_selected` | Rerun the step 4 provisioner with `--browser-project` and `--browser-identity` |
| `identity_browser_helper_unreadable` | `yoke browser devtools` returned no readable receipt: check the installed Yoke at the named path and SSH, then rerun |
| `test_machine_sign_in_app_quit_not_proved` | Close every Chromium window, answering its prompts, then rerun; it is never force-killed |
