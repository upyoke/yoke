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

If they have no `curl` / no `sh`: the documented command never starts. Public
doc (`docs/public/install.md`): "Prerequisites: a shell, `curl`, and `uv`
(the installer can install `uv` with consent)." Windows is not listed.

No wizard questions occur.

## Transcript — `/yoke onboard`

Does not run. There is no Windows harness install path in this installer.

After WSL, the transcript is A01 (create project, skip GitHub, skip hosting)
with Linux PATH files (`.profile`) instead of `.zprofile`.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Supported OS | Installer `uname` gate | Current fail string | Same string **plus** WSL install + rerun `curl -fsSL https://upyoke.com/install \| sh` inside Ubuntu |
| Deploy / env | N/A — never onboarded | — | Same as A01 once on WSL |

Ledger: G-windows-native-install, G-windows-wsl-teaching.
