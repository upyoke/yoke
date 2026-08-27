# A03 — Marcus, AI-native startup, AWS, GitHub Actions, CI/CD

**Vector:** AI-native startup · active product · AWS · macOS laptop / Linux CI ·
GitHub with CI · CI/CD.

Marcus already ships to AWS from Actions. He wants Yoke as the control plane
for agents, not a second deploy system — or he will accept Yoke-owned OIDC if
it maps onto the existing account.

## Fit / break / gaps

| | |
|---|---|
| Fits | Local or upyoke.com. Existing folder + GitHub App. AWS accepts guided or existing access keys. Packs `registry-oidc` / `production-deploy`. `/yoke onboard` gated apply. |
| Breaks | Existing access keys work, but existing OIDC, SSO, instance profiles, and role assumption do not. Profile assumes Yoke-owned stage+prod even when the company already has them. |
| Gaps | Bring-your-own non-static AWS identity. Mapping existing Actions workflows as hints only (must not parse `.yoke/deployment-flows.json` as contract). |

## Transcript — installer

`curl -fsSL https://upyoke.com/install | sh` on Darwin. uv present.
`Starting Yoke onboard…` → `yoke onboard --post-install`.

## Transcript — wizard

Install summary Continue. PATH OK Continue.

Account — two honest lanes:

**Lane A (this machine):** This machine → local universe Continue.

**Lane B (cloud for the team):** `upyoke.com` / `hosted by Yoke · private beta`.
Browser approval (`onboard_wizard_flow_hosted_machine`). No token paste
("Yoke never asks you to paste a GitHub secret" is GitHub; hosted machine
approval is browser). Private beta may block if he has no code.

This transcript continues **Lane A** (founder laptop) plus later Cloud as a
second home ("you can add another later").

GitHub: **Connect GitHub.** Device code + App install on `acme/app`.

Project: Existing folder `~/src/acme-app`. Origin matches. **Use connected
repo.** Prefix `ACME`. Board art Mixed. Hosting:

```
Connect your hosting provider?
  AWS
  I host this myself
  Decide later

How should Yoke sign in to AWS?
  Create a dedicated deploy key     Recommended
  Use existing credentials          An access key you manage
  Not now                           Continue without AWS credentials
```

**User:** Use existing credentials. Pastes an access key pair the team already
manages **in the wizard** (not chat). No IAM user creation link appears. Save
& verify uses the same owner-only `aws-admin` storage and in-process STS check
as the guided route.

```
✔ AWS identity verified · aws-admin saved
  Account       {account}
  Identity      {identity}
  Stored at     ~/.yoke/secrets/capability-secrets/acme-app/aws-admin/
CI never sees this key — deploys federate through short-lived OIDC
roles that Yoke provisions from it during /yoke onboard.
  Continue to Review
```

**User:** Continue. Review Apply.

Hand-off: Claude Code, Codex, or Cursor; `/yoke onboard`.

## Transcript — `/yoke onboard`

Checklist init `--project acme-app`.

Survey sees `.github/workflows/deploy.yml`, Terraform or CDK, `package.json`.
Strategy docs from the running product.

Profile (stop 1): scaffold mapped `not-needed`; infra Packs; `aws-admin`
already verified (`yoke aws exec --project acme-app -- sts get-caller-identity`).
Environments stage+prod. Domain default subdomain
`yoke projects environment-settings merge … --set domain.mode=default-subdomain`.

Step 5: `yoke packs get registry-oidc {checkout} --project acme-app` then
`--apply`. `yoke deployment-flows create {flow_id} --stages-file … --target-tier
persistent --environment stage`. `yoke project-structure patch apply` for
`deploy_defaults`.

Step 7 gate `[y/N]` defaults **No**. Preview: Pulumi/stacks, OIDC provider,
CI roles. **User:** yes. Apply + first stage deploy + smoke.

If he declines: `infra-apply-first-deploy=deferred`; seed still runs. Items
still get the project default flow from step 5. Usher Route B then requires
the pipeline even though infra was never applied — **blocker** unless flows
are merge-only or unset.

Seed: `yoke items create … --deployment-flow {default}`.

## Test setup

**Reality:** active product. Likely Jest or pytest plus
`.github/workflows/deploy.yml` (and maybe a test workflow). CI already
deploys.

**Bind today:** register the **test** argv as `quick`/`full`. Declare
`ci_workflow_file.workflow_file` only for the workflow that runs that
suite (not the deploy workflow). `command-ci` then `ci_run`. `merge_queue`
only if the org already uses merge-when-ready and the workflow has
`merge_group`.

**Onboard:** survey sees CI as a deploy **hint**. Step 5 does not write
`ci_workflow_file`. Seed will not attach `registered-command-quick`.

**Ask that should happen:** "Which workflow is the required status check?
Which local argv is `quick` vs `full`? Queue or standalone merge?" Refuse
binding `command-ci` to a deploy-only YAML.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| AWS apply | Hosting verified + step 7 explicit yes | Gate default No; `deferred` does not block seed | Do not assign persistent default flow until apply succeeded |
| Existing CI | `.github/workflows` is a **hint**, not a Yoke flow | Do not fail onboard if Actions already deploy | Map or ignore; never dual-write two production pipelines silently |
| Migration | If the app has Postgres, `migration_model` is a project capability — not asked here | Rehearsal refuses HTTPS product connections | Declare model later; idea items that mutate DB need a DB claim |

Ledger: G-byo-aws-identity, G-no-deploy-default-flow (deferred apply), G-installer-handoff-cursor, G-test-setup-unasked, G-ci-workflow-undeclared, G-command-ci-misbind.
