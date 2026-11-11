# Production Deploy Pack Checklist

Complete this checklist in the target project before treating either installed
workflow as production-ready.

## 1. Confirm the Pack plan

- [ ] production-deploy and its dependencies appear in .yoke/packs.json.
- [ ] The project reviewed every installed workflow, script, and document.
- [ ] The Compose layout, remote directory, API and web ports, health routes,
      and Docker project name match the actual application.
- [ ] Project-specific deployment, rollback, recovery, backup, and incident
      runbooks live in the project repository.

## 2. Confirm GitHub and AWS authority

- [ ] Both workflows grant only contents: read and id-token: write.
- [ ] The production GitHub environment has the project's required reviewer
      and branch protection.
- [ ] Repository variable YOKE_DELIVERY_CI_ROLE_ARN equals the registry-oidc
      Pack's exact delivery-role output for this repository.
- [ ] The role trust policy admits only the intended repository and production
      environment subject.
- [ ] The repository does not supply AWS_ACCESS_KEY_ID or
      AWS_SECRET_ACCESS_KEY to either workflow.
- [ ] The pinned checkout and AWS credential actions are reviewed immutable
      revisions.

Use the project's sanctioned exact-stack Pulumi boundary for preview, apply,
and readback:

    yoke pulumi exec --project <project> --stack <registry-stack> -- preview
    yoke pulumi exec --project <project> --stack <registry-stack> -- up --yes --non-interactive
    yoke pulumi exec --project <project> --stack <registry-stack> -- stack output

## 3. Confirm SSH delivery inputs

The installed VPS workflow needs three project-specific GitHub secrets:

- [ ] <PREFIX>_SSH_HOST
- [ ] <PREFIX>_SSH_USER
- [ ] <PREFIX>_SSH_KEY

The private key must be limited to the intended host and deploy user. Do not
store it in project files, Pack source, Pack receipts, or Yoke DB settings.
Record rotation and revocation procedures in the project.

## 4. Prepare the target host

- [ ] Docker, Compose, nginx, rsync, Python, and the project's runtime
      prerequisites are installed.
- [ ] The deploy user owns the application directory and can run the required
      Docker operations.
- [ ] The host-maintenance Pack's installed helper has been reviewed.
- [ ] Production data and secrets are outside rsync's delete authority.
- [ ] Backup and restore have been rehearsed on a non-production target.
- [ ] Direct origin access, firewall policy, TLS, DNS, and CDN origin behavior
      match the project's threat model.

Use files installed by the relevant Packs from the project checkout; do not
fetch a central copy at deployment time.

## 5. Verify required CDN behavior

- [ ] The configured CloudFront distribution belongs to this project.
- [ ] ops/cloudfront_invalidate.py is present from domain-cdn-edge.
- [ ] The delivery role can discover and invalidate the required distribution.
- [ ] Missing distribution identifiers, denied AWS calls, and invalidation
      failures leave the workflow red.

## 6. Exercise both paths

- [ ] Preview the normal deployment source change and commit it.
- [ ] Run the configured normal Yoke deployment flow and record its run,
      workflow, commit SHA, and health evidence.
- [ ] Run the configured hotfix flow with a real Yoke dispatch correlation id.
- [ ] Confirm the deployed marker and service health identify the expected SHA.
- [ ] Confirm CloudFront invalidation completed under the assumed role.
- [ ] Confirm no static AWS key secret was read.
- [ ] Confirm a failed health gate or invalidation produces a failed workflow.

## 7. Own the result

- [ ] Replace generic examples in these docs with the project's real commands
      and contacts.
- [ ] Run the Pack verification entrypoints and the project's own tests.
- [ ] Commit installed source and .yoke/packs.json together.
- [ ] Preview future updates with yoke packs update production-deploy; never
      treat local customization as central drift.
