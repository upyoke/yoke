# Idea — Infer Deployment Flow

```text
yoke project-structure deploy-defaults get --project "$_project"
```

Attach only an active flow that fits the request, judged by its fields, not
its id. Otherwise omit `--deployment-flow`; NEVER store `none`. Task items
omit it. Requests that need more: [delivery-requirements.md](delivery-requirements.md).
