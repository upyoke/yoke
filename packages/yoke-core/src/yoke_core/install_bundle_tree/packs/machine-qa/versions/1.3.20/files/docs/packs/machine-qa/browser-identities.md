# Browser identities on test machines

A browser identity is one persona's whole browser profile, signed into every
site that persona uses. A project declares its identities, each with a
signed-in check per site, in its `browser-control` capability settings; the
product reference `docs/public/reference/qa-platform/browser-identities.md`
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
- [macOS, step 11](macos-host-provisioning.md#11-live-browser-identities)
- [Windows/WSL2, step 6](windows-host-provisioning.md#live-browser-identities-inside-wsl)

Agents do every step that does not need the user; personal credentials are
entered by the user, and only for the sites the check reports expired. Profile
data stays on the host. Tests use agent captures; human viewing serves only a
requested, announced personal sign-in handoff, never a test acceptance check.
