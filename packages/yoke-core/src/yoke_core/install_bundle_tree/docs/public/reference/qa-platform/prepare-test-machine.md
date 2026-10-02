# Prepare a test machine

Before saving a whole-home golden, prepare the dedicated test account. Saving
files does not renew sign-ins or repair a login keychain. Repeat this checklist
after passwords, credentials, harness installs, or desktop tools change.

## Every OS

1. Install Python 3 and Claude, Codex, and Cursor CLI for the test user. Make
   their executables available in that user's PATH or `~/.local/bin`.
2. Sign in each harness in the test user's session: `claude auth login`,
   `codex login`, and `agent login` (or `cursor-agent login`). Each must answer
   a real request; a successful status string is insufficient.
3. Have the operator accept Claude's one-time bypass-mode warning on this
   isolated test account. The check reads the user setting
   `skipDangerousModePermissionPrompt`; it never writes it or accepts a prompt.
   See [Claude's settings reference](https://code.claude.com/docs/en/settings-reference#skipdangerousmodepermissionprompt).
4. Remove Yoke installation/session residue before capture. Retain the
   signed-in harnesses and the account's remote-access credentials.

## Linux

- On a desktop host, install `xdotool` along with the desktop provisioning
  prerequisites. Desktop packages persist outside the saved home. The input
  check also runs when the desktop is logged out; a headless Linux host needs
  no desktop input tool.
- Leave the test user's desktop available when its QA needs GUI input. Harness
  requests execute in the SSH user session; the GUI case uses the provisioned
  desktop.

## macOS

- Sign in harnesses from **Terminal.app in the logged-in GUI account**, using
  its unlocked login keychain. SSH authentication errors alone do not prove
  that a GUI sign-in is broken. Leave that session and its Terminal bridge ready.
- Whenever the account login password changes, have the operator update the
  login keychain password too. In Keychain Access, change the `login` keychain
  password using its old password and the account's new password. If the old
  password is unavailable, the operator must create a new login keychain and
  sign in each harness again. A new keychain loses its old stored credentials.
- Prove Claude's credential is readable from GUI Terminal, then save a new
  golden. Restoring a golden from before the password change also restores the
  old-password keychain; retire its use and capture again after re-keying.

## Windows / WSL

- Prepare the non-root default user inside the Windows SSH account's default
  WSL2 distro. Install Python 3 and all three harness CLIs and sign in there.
  Accept Claude's warning there too. The saved home and probes belong to WSL;
  Windows credentials, WSL registration and the Windows desktop are outside
  the reset boundary.
- Prepare an unlocked Windows desktop separately when QA needs desktop input.

## Capture and prove the roundtrip

Read each operation's `--help` before choosing paths or reset options.

```text
yoke test-machine golden-capture --project P --machine NAME --destination /absolute/path/outside/test/home
yoke test-machine reset --project P --machine NAME --baseline fresh-host
yoke test-machine verify --project P --machine NAME
```

Omit `--destination` for subsequent captures to use a new dated sibling of the
registered golden. A successful capture registers only the new proven golden.
Reset restores that saved home and repeats its sealed probes; verify proves
the restored state is usable. Keep the capture, reset and verify receipts.

Without `--probes-file`, capture seals the standard set for the declared OS:

| Check name | Required on |
| --- | --- |
| `Claude real request` | All |
| `Codex real request` | All |
| `Cursor real request` | All |
| `Claude bypass accepted` | All |
| `macOS login keychain readable` | macOS, through GUI Terminal |
| `Linux desktop input available` | Linux; passes without a desktop |

For extra checks, start from the current `.probes` JSON sidecar and add entries
to its `probes` list. A supplied file must include every standard check name;
missing names refuse as `baseline_standard_probes_missing`. Capture always
runs/seals the canonical standard programs, preserving additional checks.
It never carries forward an older sidecar implicitly. A failing standard check
names the checklist step to repair; no failed check can register a new golden.
Harness output and keychain credential contents stay on the test host.
