# Web Application Environment Setup

Each environment stack combines an existing VPS stack with managed Postgres,
the API edge, an origin role and instance profile, logs, and a private artifact
bucket. Optional settings add distribution publishing, a GitHub App secret,
and wildcard preview DNS permissions.

Use Yoke's capability-owned Pulumi command for preview, apply, and refresh:

    yoke pulumi exec --project <project> --stack <stack> -- preview
    yoke pulumi exec --project <project> --stack <stack> -- up --yes --non-interactive
    yoke pulumi exec --project <project> --stack <stack> -- refresh

Review every proposed cloud change before applying it and require a clean
refresh preview afterward.

## Project-specific work

- Choose environment names, domains, database size and retention, artifact
  retention, and whether the stack is active or render-only.
- Create or import the referenced VPS stack and confirm its output names.
- Decide which security groups may reach the database and which repositories
  or distribution buckets the origin may access.
- Configure backup, restore, deletion protection, maintenance windows, alarms,
  incident response, and environment recovery for the real product.
- Review IAM and bucket policies against the project's data classification.
- Import existing cloud resources with their exact provider identifiers rather
  than creating duplicates.
