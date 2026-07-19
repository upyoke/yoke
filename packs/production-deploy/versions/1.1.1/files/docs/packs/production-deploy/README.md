# Production Deploy Pack

Provides preview-first production deploy and hotfix workflows, deployment
verification, and reusable operator guidance.

The Pack depends on container-runtime, host-maintenance, registry-oidc, and
domain-cdn-edge because its workflows build the Compose application, converge
host cleanup, assume the delivery role, and require CloudFront invalidation.

## Install

    yoke packs get production-deploy /path/to/project --project <project>
    yoke packs get production-deploy /path/to/project --project <project> --apply

The first command previews this Pack and any missing dependencies. Review the
whole plan before applying it.

## Flow integration

The installed workflows accept Yoke's durable dispatch marker. Every
`github-actions-workflow` stage that points at the deploy or hotfix workflow
must declare the matching input in the project's
`.yoke/deployment-flows.json`:

```json
{
  "executor": "github-actions-workflow",
  "workflow": "<project>-deploy.yml",
  "dispatch_correlation_input": "yoke_dispatch_id",
  "reconcile_by_head_sha": false
}
```

Use both fields for a post-deploy smoke workflow. The correlation marker lets
Yoke recover a lost dispatch response; disabling head-SHA reuse ensures every
new deployment gets its own verification instead of reusing an older result
for the same commit.

## Project-specific work

- Set the real protected branches, host secrets, role variable, paths, ports,
  health checks, and smoke paths.
- Reconcile build and restart commands with the project's runtime architecture.
- Confirm the project's CDN is in scope. This Pack treats invalidation as
  required and fails closed.
- Configure GitHub environment protection and the OIDC trust policy together.
- Keep final deploy, rollback, recovery, and incident runbooks in the project
  repository and prove both deploy and hotfix paths there.

The installed workflows are starting points, not a universal deployment
package. If a project does not use this VPS, Compose, and CloudFront topology,
it should not install this Pack or should replace the installed source with its
own project-owned delivery implementation.
