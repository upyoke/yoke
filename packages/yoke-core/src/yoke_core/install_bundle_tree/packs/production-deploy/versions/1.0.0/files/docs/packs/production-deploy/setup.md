# Production Deploy Pack Setup

## Prerequisite Packs

production-deploy declares the capabilities its workflows directly consume:

- container-runtime for Compose application source;
- host-maintenance for safe Docker cleanup;
- registry-oidc for the repository delivery role; and
- domain-cdn-edge for CloudFront discovery and invalidation.

yoke packs get installs missing dependencies after showing one combined
preview.

## Project settings

Before installation, register the real project name and display name, API and
web ports, web health path, additional smoke paths, AWS region, CloudFront
distribution id, and immutable action revisions in the project's Yoke settings.
The Pack descriptor is the exact settings contract.

Provider secrets do not belong in those settings. AWS workflow authority comes
from OIDC, while SSH material stays in repository/environment secrets under the
project's own names.

## Install

    yoke packs get production-deploy /path/to/project --project <project>
    yoke packs get production-deploy /path/to/project --project <project> --apply

Review the workflow names and targets before apply. The installed source is
project-owned and should be committed with .yoke/packs.json.

## Provision OIDC authority

Use the registry-oidc program installed under infra/ through the exact-stack
Yoke Pulumi boundary:

    yoke pulumi exec --project <project> --stack <registry-stack> -- preview
    yoke pulumi exec --project <project> --stack <registry-stack> -- up --yes --non-interactive

Read back the delivery-role and repository-variable outputs. Confirm the
repository variable YOKE_DELIVERY_CI_ROLE_ARN matches that exact role before
dispatching either workflow.

## Configure GitHub

Create a production environment with the project's protection rules. Add only
the SSH host, user, and private-key secrets required by this VPS workflow. Do
not create static AWS access-key secrets for delivery.

## Prepare the host

Provision the host through the project's selected VPS and infrastructure Packs.
Ensure Docker, Compose, nginx, rsync, and Python are present, the deploy user has
only the required permissions, and production data is outside rsync delete
scope. Rehearse backup and restore before the first production run.

## Configure Yoke delivery

Bind the normal and hotfix workflows to project-local deployment flows. The
exact flow ids, stages, approval policy, and verification belong to the project;
this Pack intentionally does not invent them.

## Prove setup

Run both normal and hotfix paths from real Yoke deployment runs. Verify the
exact SHA, host health, public health, assumed role, and CloudFront invalidation,
then retain the project-specific receipts in its runbook.
