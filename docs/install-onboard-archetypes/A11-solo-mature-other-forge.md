# A11 — Pat, solo mature side project, DigitalOcean, Linux, Bitbucket, manual deploy

**Vector:** solo · mature · DO/VPS · Linux · **other forge (Bitbucket)** ·
manual.

Pat's PHP app lives on Bitbucket Cloud, deploys with `git push dokku`. No
GitHub account they want to use.

## Fit / break / gaps

| | |
|---|---|
| Fits | Linux install. Existing folder. Skip GitHub. Skip AWS hosting. |
| Breaks | Clone-from-GitHub cannot list Bitbucket. App bind cannot see `bitbucket.org`. Dokku is not AWS and not a Yoke flow. `vps-hosting` is EC2. |
| Gaps | Generic git remote. Dokku/manual PaaS-on-VPS. |

## Transcript — installer + wizard

Linux. This machine. **Skip GitHub.**

Project: Existing folder `~/sites/pat-wiki`. Remote
`git@bitbucket.org:pat/wiki.git`. Not GitHub origin → no
`project_github_repo`. Publish **No**. Branch `main`. Prefix `PATW` (from
slug). Board art. Skip hosting. Apply.

GitHub automation disabled. Bitbucket Pipelines (if any) stay unknown.

`/yoke onboard`: survey sees `composer.json` and dokku `Procfile`. Confirm
no Yoke-managed host, exclude AWS Packs and choose merge-only or no default.
Verify that delivery choice; Dokku remains operator-owned.

## Test setup

Survey the actual PHPUnit suite and register its project-local argv when reliable. Known-red or materially flaky suites stay review-only, retaining roots and exact advisory command. Offer scaffold or operator-attested no-tests only when the suite is absent. Bitbucket Pipelines cannot bind ci_workflow_file, command-ci or the GitHub merge queue.

The confirmed profile, command/CI binding and immutable QA attachment follow
[test-setup.md](test-setup.md); this example is not a live setup receipt.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| GitHub | Skip | Disabled sync | Bitbucket remains VCS |
| DO/Dokku env | Missing provider | Skip cloud apply | Manual dokku; merge-only |
| Merge | Local default branch | No GitHub PR | `git push` to Bitbucket as now |

Ledger: G-forge-github-only, G-hosting-aws-only, G-no-deploy-default-flow.
