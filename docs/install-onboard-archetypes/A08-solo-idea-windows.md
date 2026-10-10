# A08 — Sam, solo, idea-only, native Windows, no remote, no deploy

**Vector:** solo · idea-only · hosting none · **Windows** · no remote · none.

Sam heard "curl the installer" from a blog. PowerShell, no WSL yet.

## Fit / break / gaps

| | |
|---|---|
| Fits | Nothing on native Windows. Same product fit as A01 **after** WSL. |
| Breaks | Installer OS gate. Hand-off never reached. |
| Gaps | Windows teaching. WSL-first install doc from the fail line. |

## Transcript — public installer

```
curl -fsSL https://upyoke.com/install | sh
```

If Git Bash/`uname` reports a non-Darwin/Linux kernel:

```
☀ native {os_name} is not supported by this installer. WSL follows the Linux path.
```

Exit 1.

If they have no `curl` or `sh`, the command never starts. The installer needs
the supported shell/OS path and installs uv automatically when absent.

No wizard questions occur.

## Transcript — `/yoke onboard`

Does not run. There is no Windows harness install path in this installer.

After WSL, the transcript is A01 (create project, skip GitHub, skip hosting)
with Linux PATH files (`.profile`) instead of `.zprofile`.

## Test setup

Native Windows never reaches onboarding in this installer. After WSL, confirm the same explicit posture as A01: offer a minimal scaffold, bind its actual suite or record the operator's no-tests reason. No silent default or invented CI binding.

The confirmed profile, command/CI binding and immutable QA attachment follow
[test-setup.md](test-setup.md); this example is not a live setup receipt.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Supported OS | Installer `uname` gate | Current fail string | Same string **plus** WSL install + rerun `curl -fsSL https://upyoke.com/install \| sh` inside Ubuntu |
| Deploy / env | N/A — never onboarded | — | Same as A01 once on WSL |

Ledger: G-windows-native-install, G-windows-wsl-teaching.
