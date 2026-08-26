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

`/yoke onboard`: survey sees `composer.json`, dokku `Procfile`. Profile AWS
list is wrong. Defer hosting. Do not create flows.

## Test setup

**Reality:** mature PHP — maybe PHPUnit locally; Bitbucket Pipelines if
any. No GitHub Actions.

**Bind today:** local `command` wrapping `./vendor/bin/phpunit` if that
exists. `ci_workflow_file` cannot name Bitbucket. `merge_queue` impossible.

**Onboard:** survey may see `phpunit.xml`; nothing registers it.

**Ask that should happen:** register PHPUnit as `quick`, or attest
no-tests if the suite is absent/red. Refuse `command-ci`.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| GitHub | Skip | Disabled sync | Bitbucket remains VCS |
| DO/Dokku env | Missing provider | Skip cloud apply | Manual dokku; merge-only |
| Merge | Local default branch | No GitHub PR | `git push` to Bitbucket as now |

Ledger: G-forge-github-only, G-hosting-aws-only, G-no-deploy-default-flow, G-test-setup-unasked, G-legacy-suite-unmapped, G-command-ci-misbind.
