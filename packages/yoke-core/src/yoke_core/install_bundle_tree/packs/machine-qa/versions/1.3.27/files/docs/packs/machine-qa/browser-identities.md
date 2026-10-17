# Browser identities on test machines

A browser identity is one persona's whole browser profile, signed into every
site that persona uses. A project declares its identities, each with a
signed-in check per site, in its `browser-control` capability settings; the
product reference `.yoke/docs/verification/browser-identities.md`
owns the declaration shape and the `yoke browser verify` and `yoke browser
authorize --identity NAME` commands.

A test machine keeps identities live in `~/.yoke-browser-identities`, outside
`~/.yoke`. The full reset keeps that store the way it keeps harness logins and
golden capture never includes it, because sites rotate session cookies and a
restored copy of a session is stale. Nothing is sealed or restored: once a walk
installs Yoke, each identity's profile path links into the store, so sessions
the site refreshes during a walk persist. Setup and first sign-in live in the
complete per-OS procedures:

- [Linux, step 5](linux-host-provisioning.md#5-optional-live-browser-identities)
- [macOS sign-in procedure](#macos-sign-in-procedure)
- [Windows/WSL2, step 6](windows-host-provisioning.md#live-browser-identities-inside-wsl)

Agents do every step that does not need the user; personal credentials are
entered by the user, and only for the sites the check reports expired. Profile
data stays on the host. Tests use agent captures; human viewing serves only a
requested, announced personal sign-in handoff, never a test acceptance check.

## macOS sign-in procedure

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
   the installed declaration reference
   `.yoke/docs/verification/browser-identities.md`.
3. For each identity, agents run `yoke browser authorize --project P
   --identity NAME` as the test user in the real headed desktop; read
   `--help`. It checks every declared site first and opens a window only for
   the expired ones, naming the identity, the site and the account; no
   automated browser runs while it is open. The user supplies personal
   credentials and completes personal approval prompts. Agents prepare the
   desktop and run the declared checks; use project-approved test accounts
   and follow project-owned sign-in policy. Keep profile data on the host.
4. The user closes every authorization window; the command checks each site
   again and fails naming any still signed out. The identity's profile path
   links into the store, so the sign-in already lives there: nothing is
   captured, sealed or restored.
5. A reset removes `~/.yoke` and keeps the store. Once a walk installs the
   candidate, `yoke browser verify --project P --identity NAME` proves each
   site still signed in, and sessions a site refreshes during the walk persist
   in the store whether the walk passes, fails or is aborted.
6. Agents perform application steps that do not need the user. An expired site
   is a precise `HUMAN_GATE` naming the machine, identity, site, account and
   resume state; the resume is `yoke browser authorize --identity NAME` on that
   host. Runtime and inventory failures retain their named diagnostics.

Use the logged-in, unlocked test-user desktop through Screen Sharing and the
GUI Terminal context; the login keychain remains that user's.

Return to [macOS host provisioning](macos-host-provisioning.md#11-live-browser-identities).
