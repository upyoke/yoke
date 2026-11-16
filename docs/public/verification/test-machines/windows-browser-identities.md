# Native Windows browser identities

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows browser identities
<!-- /yoke:breadcrumbs -->

For WSL, follow [WSL browser identities](windows-wsl-browser-identities.md).

Return to [native Windows provisioning](windows-native-host-provisioning.md).
These identities belong to the standard Windows test user and its native
headed Chromium. WSL browser profiles are separate and prove no native sign-in.

Create `%USERPROFILE%\.yoke-browser-identities` once as the test user,
restrict it to that user and Administrators/SYSTEM, and keep it outside
`.yoke`. The native profile reset preserves this **live** identity store;
golden capture excludes it. Restoring a copy of rotated cookies is not a
valid way to preserve a sign-in.

Declare each project identity and its per-site sign-in checks in the project's
`browser-control` capability; see [browser identities](browser-identities.md).
Install the candidate and prepare its Windows Chromium runtime through leased
product operations. First prove that the browser visibly renders on the
native desktop; an SSH process or an Edge sign-in does not prove that.

As the test user, in the native desktop, run:

```text
yoke browser authorize --project P --identity NAME
```

Read `--help`. The command checks declared sites and opens authorization only
for expired ones. Agents drive setup and navigation; Ben enters his own
password or credential. No automated browser runs while authorization owns
the profile. Keep cookies and profile contents on the VM, outside evidence.
Close authorization through its product flow so the command verifies each
site and preserves the identity in its live store.

After a profile reset and candidate install, prove continuity with:

```text
yoke browser verify --project P --identity NAME
```

Newly refreshed sessions stay in the live store whether QA passes, fails or is
interrupted. Reauthorize an expired identity on the same native desktop;
request a human gate only for the credential Ben must enter, naming the
machine, identity, site, account and resume point. A missing desktop, browser
runtime or identity retains its named failure and recovery. Never export a
personal host browser profile or silently substitute a WSL profile.
