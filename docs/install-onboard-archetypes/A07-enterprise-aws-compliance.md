# A07 — Omar, large enterprise, AWS, GitHub Enterprise, Linux, CI/CD

**Vector:** large enterprise · mature · AWS · Linux · GitHub with CI · CI/CD.

Omar's org has GitHub Enterprise Cloud or GHE, org SSO, mandatory CODEOWNERS,
and a landing AWS org with SCPs. They evaluate Yoke Cloud vs a team server.

## Fit / break / gaps

| | |
|---|---|
| Fits | Linux install. Hosted destination (private beta may block). Team server. GitHub App **if** the installation is allowed on the org. AWS can honestly remain deferred. |
| Breaks | App install may be forbidden by org policy (GitHub App unavailable / pending rows). Both supported AWS routes still require long-lived access keys. Hosted `upyoke.com` private beta / data residency. |
| Gaps | GitHub Enterprise GHES hostname as origin. BYO roles (no IAM user). Enterprise SSO teaching. |

## Transcript — installer

Linux + uv present. Wizard.

Account: **upyoke.com** (`hosted by Yoke · private beta`), an existing team
server, or guided self-host first boot on the intended Linux host. The guided
route previews the loopback-only server and leaves VPN/LAN/TLS to the operator;
security can use the manual `yoke self-host init` reference instead.

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

If App is allowed: bind `org/monorepo`. Hosting: choose **AWS**, then the AWS
screen offers a dedicated deploy key, an existing access key pair, or **Not
now**. Security forbids both static-key routes, so the user chooses **Not now**.
No fake `aws-admin` row is written, and the wizard does not imply that instance
profiles, SSO, OIDC, web identity, or role assumption work.

Apply still creates the project. `/yoke onboard` records
`hosting-setup=deferred`, skips the credential probe and cloud apply, and keeps
seed work legal with a merge-only flow or no default. Step 7 remains
unreachable until the operator supplies a supported access key or Yoke gains a
non-static execution path.

## Test setup

**Reality:** monorepo — many suites (unit / contract / integration),
CODEOWNERS, required status checks, possibly containerized. GitHub Actions
or an internal Actions runner fleet.

**Bind today:** `ci_workflow_file` plus optional `scope_workflows` for
`quick` vs `full`. `merge_queue` only if the org already uses the GitHub
merge queue and the workflow has `merge_group`. Local `command` must name
the same slice CI runs, or the gate diverges.

**Onboard:** bind `org/monorepo` does not ask which workflow is required.
If the App is skipped, `command-ci` and `merge_queue` are unreachable
(named reason).

**Ask that should happen:** required-check filename; `quick` vs `full`
argv; queue vs standalone. Refuse mapping one `pytest` to a 40-job
monorepo. G-legacy-suite-unmapped (many suites), G-merge-queue-github-only
when App is forbidden.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| GitHub App on the org | Machine GitHub step | Skip; `disabled` binding; pending install URL | Self-hosted GitHub origin config (not asked in wizard) |
| AWS credentials | AWS level: guided key, existing access key, or Not now | Choose Not now; step 7 unreachable | Role assumption / no-static-key execution remains unsupported |
| Data residency | Destination picker (local / existing server / guided self-host / upyoke.com) | Hosted beta refusal; guided setup refuses missing Docker before writes | Team server on-prem with enterprise-owned networking/TLS |
| Migration | Step-2 governed-database box, recorded on `migration-model-setup` | Unsupported authoritative kinds refused by name | Declare the model, name it for later, or record `not-needed` with the reason |

Ledger: G-byo-aws-identity, G-forge-github-only (org App policy), G-enterprise-static-keys, G-test-setup-unasked, G-ci-workflow-undeclared, G-legacy-suite-unmapped, G-merge-queue-github-only.
