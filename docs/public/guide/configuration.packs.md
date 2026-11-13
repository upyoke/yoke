# Packs

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Packs
<!-- /yoke:breadcrumbs -->

Packs supply reusable project files and guidance for a capability or stack. They help your agent start from a maintained implementation, while the installed files become part of your project and can evolve with it.

## What a Pack supplies

A Pack can supply application scaffolding, infrastructure definitions, scripts, tests, and documentation. Its manifest describes the version and how the files are specialized for a project.

Use a Pack when its purpose matches the project. Onboarding can select an appropriate scaffold or map an existing application without forcing it into a conflicting template. Available Packs do not imply that every project needs their infrastructure or provider accounts.

Preview the files and required settings before applying a Pack. Infrastructure changes still need the relevant configuration and approval; obtaining source files is not the same as deploying resources.

## Install settings versus runtime settings

Install settings specialize generic Pack source for the project. Runtime settings tell the installed application or Yoke capability how to operate. Credentials belong to the relevant capability's secret store, not to Pack template values or committed configuration.

Bundle fetch builds the render value groups used by the selected Pack version. Incomplete settings for unrelated infrastructure do not block a Pack update. If a required value cannot be built, `pack_bundle_failed` names the invalid setting and the settings command to correct it before retrying.

For example, a Pack may install infrastructure source while the project's capability and environment settings identify which provider and destination to use. Keep those responsibilities separate so a source update does not silently replace deployment credentials.

See [Projects](configuration.md) for settings, capabilities, and secrets.

## Versions and updates

Pack versions are immutable. A project chooses when to adopt a newer version, and its installation record keeps the baseline needed to compare that version with both the installed source and project edits.

Updates use a three-way comparison so project changes can be reconciled with upstream Pack changes. Review the resulting changes and resolve conflicts rather than copying a new template over edited files. Keep related Pack updates together when their documented contracts require it.

Use the Pack command's preview and help to inspect the proposed update. Released catalog versions are the normal path; unreleased source versions have separate source-development rules.

New versions of Webapp Scaffold and Smoke Testing bound outside package installs and downloads, limit retries, report fetch failures, and set time limits on workflow jobs. Existing projects receive these changes by running `yoke packs update PACK --project NAME --apply` and resolving any merge conflicts. Nothing updates automatically.

## Removing a Pack

`yoke packs remove PACK --project NAME` previews which records it would drop and lists the files the Pack used to own. Add `--apply` to drop the Pack from `.yoke/packs.json` and from the server's install record. No project file is deleted or changed: the former Pack files stay as ordinary project files, and you delete them yourself if you no longer want them.

Removal refuses while another installed Pack depends on the Pack, and when another installed Pack's recorded version cannot be read from the catalog, because its dependencies are then unknown. A Pack that has left the catalog can still be removed.

## Pack-owned documentation

Read the Pack's documentation for its setup, prerequisites, configuration, and update requirements. General Yoke docs explain the shared mechanisms; a Pack's own docs explain the resources and code it supplies.

When a reusable improvement belongs in the Pack, publish it as a new Pack version so other projects can choose to adopt it. A project-specific change can remain in the installed project files.

See [capabilities](../projects/capabilities.md), [Installation and setup](setup.install.md), and [Command and technical reference](reference/index.md).
