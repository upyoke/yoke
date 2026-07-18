# Managed Deployment Artifact Refresh

Use this operation for deployment references, workflows, ops programs, and
static infrastructure rendered from the active packaged template plus the
project's DB-backed settings. Project-authored deployment help stays in the
project's own `.yoke/runbooks/`; generic rendered references use the distinct
`docs/yoke-generated/deployment-reference/` namespace.

## Preview, apply, and verify

```bash
yoke project artifacts refresh ~/work/my-service --project my-service
yoke project artifacts refresh ~/work/my-service --project my-service --apply
yoke project artifacts refresh ~/work/my-service --project my-service --verify
```

Preview is the default and lists exact creates, updates, prunes, and conflicts.
Apply starts only after full path, symlink, manifest, and ownership preflight;
project-authored deviations are preserved as refusing conflicts. Planning also
requires the checkout's installed project id to match the server bundle. When
the project has a verified repository binding, its live Git origin must match.
Local or offline projects can operate without that optional binding.

The manifest at `.yoke/artifact-manifest.json` records template version plus
template, settings, and rendered-content digests. `--verify` is the CI and
external-project drift gate. The source-dev template-tree override is an
org-admin-only diagnostic and never bypasses checkout identity. This operation
is distinct from `yoke project refresh`, which updates only the managed Yoke
operating substrate.

## Adopt an existing rendered checkout

For a project that already contains earlier rendered artifacts but has no
`.yoke/artifact-manifest.json`, explicitly adopt those existing managed paths
before the first template reconciliation:

```bash
yoke project artifacts refresh ~/work/my-service --project my-service --adopt-existing
yoke project artifacts refresh ~/work/my-service --project my-service
yoke project artifacts refresh ~/work/my-service --project my-service --apply
```

Adoption writes only the manifest and records the checkout's current bytes; it
does not replace project files. The following preview shows every template
change, and the normal apply refuses if an adopted file changes in between.

## Disable the generic contract

Projects with a project-owned release factory can disable this generic webapp
artifact contract through DB-backed `project-policy` settings:
`artifact_refresh.enabled=false` plus a non-empty `artifact_refresh.reason`.
All modes then validate checkout identity and return a clean no-op receipt
without inspecting or writing the artifact manifest.
