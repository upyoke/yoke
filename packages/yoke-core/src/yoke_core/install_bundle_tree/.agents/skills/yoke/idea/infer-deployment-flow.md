# Idea — Infer Deployment Flow

Before assigning flow, read workflow-specific and project defaults:
```bash
yoke workflows mechanics get --json
yoke project-structure deploy-defaults get --project "$_project"
```

Use delivery_defaults for this project/workflow first, otherwise project default.
Task stays exempt according to its served laneless merge-free policy; leave flow
empty. A failed read blocks; successful empty stdout means no default.

Read a named candidate:
```bash
yoke deployment-flows get <flow-id> --json
```

Classify status, target_tier, target_environment, definition_schema_version
and takes_delivery_custody. An id suffix is not route authority.
Active/executable candidate attaches; disabled or unsupported stays unassigned
and is reported. Keep unsupported definitions disabled, never replace the
request with weaker delivery. Custody is independent of vocabulary version.

Empty/null target_tier is merge-only; persistent/ephemeral come from fields.
Omission **inherits** later project/workflow defaults; it does not waive
delivery. A docs/process/research title is not a merge-only exemption.
NEVER store `none`; omit `--deployment-flow` when empty.

If named environment/screenshot/verdict does not fit, follow
[delivery-requirements.md](delivery-requirements.md); do not rewrite shared defaults.
An explicit merge-only request selects an active registered empty-tier flow.

## Fallback only when both lookups found nothing

```bash
yoke deployment-flows list --project "$_project" --json
```

Inspect candidates with get, not workflow definitions. Empty list: omit flag
as inheritance, report missing default. Required environment/evidence/approval/
merge-only with no suitable supported flow is missing setup; do not invent one.
Print actual assignment and inherited-default provenance.
