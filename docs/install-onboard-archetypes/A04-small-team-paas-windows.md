# A04 — Chen, small team, PaaS, native Windows, GitHub + CI, CI/CD

**Vector:** small team · mature · PaaS (Render/Fly) · **Windows** · GitHub with
CI · CI/CD.

Chen's company ships a Node API on Render from GitHub Actions. Dev laptops are
Windows. They tried the public curl installer from PowerShell.

## Fit / break / gaps

| | |
|---|---|
| Fits | After WSL: same Linux path as A03 minus AWS hosting. Skip GitHub is wrong for them; Connect GitHub fits. |
| Breaks | **Native Windows installer exits before any wizard.** PaaS is not a hosting row. Render/Fly credentials are not `aws-admin`. |
| Gaps | Native Windows. PaaS provider. WSL teaching on the decline screen. |

## Transcript — public installer (native Windows)

Shim:

```
os_name=$(uname -s)
case "$os_name" in
  Darwin|Linux) : ;;
  *) fail "native $os_name is not supported by this installer. WSL follows the Linux path." ;;
esac
```

On native Windows `uname` is typically `MINGW64_NT-…`, `CYGWIN_NT-…`, or the
command is absent. Result:

```
☀ native {os_name} is not supported by this installer. WSL follows the Linux path.
```

Exit 1. **No** uv consent, **no** `yoke onboard`, **no** PATH doctor.

Contrast: uv-decline has a branded retry recipe (`decline_uv_and_exit`). The
OS refusal is a one-line `fail` with no WSL install steps.

Git install advice if they somehow reached project git later
(`project_git_install_advice.py`):

> Native Windows onboarding is not supported yet. Use WSL/Linux or macOS;
> inside WSL, install git with that distro's package manager.

## Transcript — only supported continuation (WSL Ubuntu)

They install WSL, then in Ubuntu: `curl -fsSL https://upyoke.com/install | sh`.
Linux passes. uv consent uses Astral (shim `YOKE_UV_INSTALLER_URL`) unless they
have brew (they don't). Default Yes. Wizard launches.

PATH: Linux `.profile`. Account: This machine (or team server if they self-host).
GitHub Connect. Project: Existing folder under `/home/chen/work/api` (clone of
GitHub). Use connected repo. Hosting: **Skip** (Render is not AWS). Apply.

`/yoke onboard`: the no-Yoke-managed-host posture omits `aws-admin` and AWS
hosting Packs. There is **no** Render/Fly Pack in the profile list, so the
team confirms **merge-only** delivery: Yoke performs the local merge with no
environment or pipeline run, while the existing Render deployment remains
external and operator-owned.

Existing Actions remain a hint. Yoke does not register a persistent Render
flow or enter the AWS approval gate.

## Test setup

**Reality:** mature app with GitHub Actions (test + maybe Render deploy) and
a local Jest/pytest suite. Native Windows never reaches this; after WSL the
suite is Linux.

**Bind today:** declare the **test** workflow as `ci_workflow_file`;
register `quick`/`full`. `command-ci` works because GitHub App + Actions
exist. Do not treat the Render deploy job as the verification workflow.

**Onboard:** no test box. After WSL, survey sees workflows and does not
write the capability.

**Ask that should happen (WSL):** which YAML is the required check; local
argv for `worktree_run` fallback. Refuse `merge_queue` unless they already
run merge-when-ready.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Supported OS | Installer OS gate | Current one-liner | WSL walkthrough + link to `docs/public/install.md`; do not imply native Windows later |
| PaaS environment | Execution profile hosting box | "No PaaS provider in the wizard; skip cloud apply" | Merge-only / empty default; keep Render as external deploy |
| GitHub CI | App binding | Unreachable CI method names the reason | `command-ci` when `ci_workflow_file` exists; else local |

Ledger: G-windows-native-install, G-windows-wsl-teaching, G-paas-hosting, G-test-setup-unasked, G-ci-workflow-undeclared, G-command-ci-misbind.
