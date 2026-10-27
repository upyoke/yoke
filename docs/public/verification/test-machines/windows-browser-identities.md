# WSL browser identities

Return to [Windows host provisioning](windows-host-provisioning.md).

A test machine keeps each project identity signed in live, outside the
clean-home golden.

1. As the test user, create the live identity store once:
   `mkdir -m 700 ~/.yoke-browser-identities` inside WSL. Never place it inside `~/.yoke`.
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

The candidate Chromium and profile both live under the non-root WSL test user.
The operator needs an actually working headed WSL display; a native Windows
Edge/Chrome sign-in cannot populate this Linux candidate profile. Prove the
Linux application visibly renders before requesting a personal sign-in. If
the provisioned WSL display is unavailable, return its named failure; do not
change system settings or invent native-profile exports. The identity store
lives in the WSL test user's home, which the Linux reset keeps.

