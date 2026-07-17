# GitHub Actions Workflows

## Included

- **ci.yml** -- Runs on push/PR to main. Backend pytest + frontend npm build.

## Deploy Workflows

Deploy workflows (production deploy, hotfix, smoke tests, ephemeral
environments) are selected from the product-safe webapp template after project
registration. Project onboarding applies project-specific substitutions and
commits the selected workflow files to the project repo.

### Generating Deploy Workflows

1. Fetch raw workflow material with `yoke templates fetch webapp --only ops/`.
2. Record project settings and capabilities through `/yoke onboard-project`.
3. Let project onboarding commit the selected workflow files and configure
   GitHub secrets/environments.

See the template [README.md](../../../README.md) for full instantiation steps.
