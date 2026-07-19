# Pulumi Foundation Environment Setup

This Pack installs shared Pulumi program source and deferred stack-file source
under infra/. Project values remain in Yoke project, site, environment, and
capability settings; provider secrets remain in capability-owned secret stores.

## Install

    yoke packs get pulumi-foundation /path/to/project --project <project>
    yoke packs get pulumi-foundation /path/to/project --project <project> --apply

The installed infra/ directory is ordinary project-owned source. Other
infrastructure Packs add their own program modules and depend on this Pack.

## Declare stacks

Declare only stacks and environment instances the project actually uses in its
pulumi-state and site/environment settings. Each live stack needs:

- a stable stack name and kind;
- an S3 backend and KMS secrets provider;
- AWS account and region;
- component-specific settings from the installed Packs;
- a reviewed activation state; and
- typed operator state after initialization.

An environment marked render-only is for review and must not be initialized or
applied until it is explicitly activated.

## Execute an exact stack

Use Yoke's capability-owned boundary:

    yoke pulumi exec --project <project> --stack <stack> -- preview
    yoke pulumi exec --project <project> --stack <stack> -- up --yes --non-interactive
    yoke pulumi exec --project <project> --stack <stack> -- refresh

The command reads the selected project's installed infra/ source, materializes
a private scratch workspace, preserves operator-owned stack metadata, and
resolves project AWS credentials without printing them. Do not run from Yoke's
central Pack catalog or copy another project's stack files.

## Initialization and imports

Initialize each live stack once through the same boundary with its approved KMS
secrets provider:

    yoke pulumi exec --project <project> --stack <stack> -- init --secrets-provider 'awskms://<kms-key>?region=<region>'

The command uses a 0700 scratch workspace and persists typed operator-state.
No repo-local infrastructure checkout or ambient AWS shell environment is
needed. For existing cloud resources, preview and use exact provider identifiers
from reviewed project settings before import; never copy encrypted operator
state between stacks.

## Required verification

Before apply, review every create, update, replace, and delete. After apply, run
a refresh preview and require no unexplained changes. Record non-secret outputs
and live behavior in the project's infrastructure runbook.

## Intentional project-specific gaps

This Pack does not choose cloud accounts, regions, topology, stack names,
capacity, import targets, deletion policy, backup, recovery, or approval
authority. Those decisions belong to the project and the component Packs it
installs.
