# Pack capabilities

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Packs
<!-- /yoke:breadcrumbs -->

Read this home before adding or updating reusable capabilities, project configuration or credential references.

## Pack-first capabilities

- **If your project distributes reusable capabilities, package them as Packs.** Reusable ops workflows, deployment tooling, and infrastructure patterns live in a focused `packs/<slug>/` bundle with immutable versions, explicit files, settings, dependencies, documentation, and verification.
- **Installed Pack files belong to the project.** They land in the target project repo and may be customized there. Yoke records the installed baseline in `.yoke/packs.json` only so that project owners can preview and apply one Pack update with a three-way merge; it does not police drift, prune files, or synchronize the whole project.
- **Improve the Pack when the general capability evolves.** Publish a new Pack version, then let each project choose whether and when to update it. Project-only behavior remains project-owned and need not flow back into the Pack.
- **Install a Pack version before its release with `--catalog`.** `yoke dev run -- yoke packs get|update ...` reads the lane's Pack catalog; `--catalog commit:SHA` adopts a version merged into the Yoke default branch but not yet released. `.yoke/packs.json` records that source, and an update from the served catalog refuses (`pack-source-unreleased`) until a release carries that exact version.
- **Project config lives in DB settings/capabilities or project-local `.yoke/` policy docs.** Use `project_capabilities`, `sites.settings`, and `environments.settings` for credentials and runtime config. Pack install settings only specialize generic source for the target project; runtime-generated files land in scratch/deploy-run output or the target project repo.
- **Provider credentials are capability-owned, not ambient shell.** For AWS, the source of truth is the project `aws-admin` capability: non-secret settings in `project_capabilities`, while secret material lives in machine-local capability secret files under `~/.yoke/secrets/capability-secrets/<project>/aws-admin/`. The `capability_secrets` table is not the storage shape for `aws-admin` secrets. A naked `aws ...` command may fail even when the project is correctly configured because the credentials are not exported into the shell. Use Yoke-owned capability resolver surfaces to materialize credentials into a subprocess env without printing secret values; when a resolver has not yet been wrapped, treat it as a source-dev/admin helper rather than an agent recipe. Verify by listing keys/settings or redacted evidence; never log raw secret values.

Plan authoring and intake materialization may record another environment on the
control plane. Standalone QA dispatch still obeys the runtime execution
restriction; deployment QA uses the run receipt to authorize its deployed target.

## Related

- [Deployment runs and packaged capabilities](delivery.md)
- [Release-time roles](release-roles.md)
