# A07 — Omar, large enterprise, AWS, GitHub Enterprise, Linux, CI/CD

**Vector:** large enterprise · mature · AWS · Linux · GitHub with CI · CI/CD.

Omar's org has GitHub Enterprise Cloud or GHE, org SSO, mandatory CODEOWNERS,
and a landing AWS org with SCPs. They evaluate Yoke Cloud vs a team server.

## Fit / break / gaps

| | |
|---|---|
| Fits | Linux install. Hosted destination (private beta may block). Team server. GitHub App **if** the installation is allowed on the org. AWS hosting keys. Packs for OIDC. |
| Breaks | App install may be forbidden by org policy (GitHub App unavailable / pending rows). One-click IAM user may violate "no long-lived keys". Hosted `upyoke.com` private beta / data residency. |
| Gaps | GitHub Enterprise GHES hostname as origin. BYO roles (no IAM user). Enterprise SSO teaching. |

## Transcript — installer

Linux + uv present. Wizard.

Account: **upyoke.com** (`hosted by Yoke · private beta`) **or** team server.

If hosted: browser machine approval. If the org is not in private beta, the
lane fails with retry/back (`HOSTED_MACHINE_RETRY_ROWS`: "Try again" /
"Back"). **User** falls back to **A team server** + token.

GitHub: Connect. Possible:

```
  Reconnect GitHub     replace saved authorization
  Skip GitHub          continue without GitHub
  Back
```

(`GITHUB_APP_UNAVAILABLE_ROWS`) if the App cannot be installed on the org.

Or pending installation (`GITHUB_APP_PENDING_ROWS`): Check access / Skip / Back.

Security team refuses the App → **Skip GitHub**. Then Yoke cannot bind Issues,
PRs, Actions variables. Enterprise GitHub remains outside.

If App is allowed: bind `org/monorepo`. Hosting: security refuses pasting
`AKIA…` into a TUI. **Skip for now** with intent to use instance roles later
— **no wizard row for instance profile / OIDC-only**.

Apply still creates the project. `/yoke onboard` hosting probe fails without
keys:

```
hosting-setup=blocked
aws-admin present but identity probe failed; re-set via:
yoke projects capability secret set --project {project} --cap-type aws-admin
  --key access_key_id --value-stdin
```

(from `hosting-and-environments.md` — only if a row exists but probe fails).
If they never saved keys: connect via the same `--value-stdin` recipe, still
long-lived keys.

Step 7 apply under `yoke aws exec` is the sanctioned resolver path — still
needs *some* `aws-admin` material on the operator machine.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| GitHub App on the org | Machine GitHub step | Skip; `disabled` binding; pending install URL | Self-hosted GitHub origin config (not asked in wizard) |
| AWS credentials | Hosting step; "paste two values" | Skip; step 7 unreachable | Named enterprise posture: role assumption / no static keys (missing) |
| Data residency | Destination picker (this machine / team server / upyoke.com) | Hosted beta refusal | Team server on-prem |
| Migration | Not in wizard | Silent | Architecture/capability later |

Ledger: G-byo-aws-identity, G-forge-github-only (org App policy), G-enterprise-static-keys.
