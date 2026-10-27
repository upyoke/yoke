# Projects

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Projects
<!-- /yoke:breadcrumbs -->

A project is a named body of work inside a Yoke Universe, with its own strategy, backlog, configuration, and guidance. Connect its repository checkouts, declare the capabilities it needs, and let agents use those shared facts across machines and sessions.

## Project identity and structure

The project record identifies the project independently of any one checkout folder. Its repository binding, item prefix, and declared structure help Yoke relate work to the correct code and delivery setup.

Project structure records describe configured facts such as test roots, hosting posture, and delivery defaults. They give agents a place to read those facts instead of inferring them repeatedly from scripts or old conversations.

A Universe can hold several projects. Dependencies and steering can coordinate their work, while each item still belongs to its own project. See [Workflows and work items](work.md) and [The Frontier](frontier.md).

## Setup and checkout connections

### Project identity versus checkout

A checkout is a repository folder on one machine. Registering it connects that location to the shared project; it does not create a separate copy of the project's backlog. Multiple machines and worktrees can refer to the same project.

### Existing project versus new project

Setup can connect an existing project or create a new one. It recognizes an existing mapping and asks how to handle repository configuration that refers to a different or inaccessible Universe. Review that choice rather than creating duplicate projects to work around an access problem.

### Install and refresh agent guidance

Project installation supplies skills, hooks, agent instructions, and installed reference docs. Refresh brings that layer up to the current serving release while checking ownership and local edits. It preserves project-owned material instead of treating every file as disposable.

Ask your agent to complete a reported partial installation or refresh before assuming the project is ready. See [Installation and setup](setup.install.md) and the [project installation reference](../start/project-install.md).

## Settings and secrets

### Machine, Universe, and project settings

Machine settings describe local connections, installed harnesses, and machine-specific behavior. Universe settings apply to shared control-plane behavior. Project settings describe one project's capabilities and delivery needs; site and environment settings specialize where that project runs.

Set a value at the scope that owns it. Copying a machine path or credential into a shared project setting can make another machine's configuration incorrect.

### Non-secret settings

Capabilities and project structure hold declared non-secret configuration. Use your agent or the typed CLI operations to read and update them. The dashboard provides useful inventories but does not offer a form for every setting.

### Secret ownership

Credentials belong to their capability and supported secret store, not to an arbitrary chat message, committed file, or Pack template. Agents should use the capability resolver to make credentials available to the command that needs them without printing their values.

A capability declaration and a usable credential are separate facts. Moving a Universe or adding a machine may require reconnecting or provisioning access rather than copying existing secrets.

### Changing settings safely

Read the current setting and its owner before updating it. Supported updates can protect against concurrent changes. Review effects on active workflows or deployments, particularly when a change alters where commands run or what credentials they use.

See [Capabilities](../projects/capabilities.md) and [Machine configuration](../cli/machine-config.md).

## Capabilities and providers

A capability declares something a project can use, such as cloud access, a migration model, CI binding, or a QA resource. It can be available, configured, deferred, or unavailable for the work at hand.

Onboarding configures what the initial work needs; it does not require every capability. The dashboard's **Capabilities** page reports readiness. Setup and changes happen through your agent or the CLI.

[Packs](configuration.packs.md) can supply reusable files and integration scaffolding, but installing a Pack and configuring its runtime credentials remain distinct steps.

## Shared project files

Shared files provide a stable project URL for material such as a review document or supporting artifact. Authorized clients of the same Universe can read the referenced bytes, so a link can be used in a work item, strategy doc, or message.

Uploading to an existing path replaces its content. Use deliberate names when a review needs a fixed version. Shared files complement repository files; they do not replace Git history for source code or move checkout folders between machines.

Storage can be local to the serving machine or backed by configured artifact storage. See [Shared files](../projects/shared-files.md) for access, size limits, and storage behavior.

## GitHub and CI

### Connect repository access

GitHub App authorization, the project's repository binding, and ordinary Git transport are related but separate configuration. Setup can connect the App, and project installation wires the supported checkout helper where applicable.

### Opt into issue mirroring

GitHub issue mirroring is optional and controlled per project. Connecting GitHub does not mean every Yoke item should automatically mirror to an issue. Disabling mirroring also does not disable the connected repository's merge and delivery requirements.

### CI execution and evidence

Declare the test workflow Yoke should use for verification. Deployment flows separately describe release actions, environments, and approvals. CI output is evidence only for the revision and work it actually checked.

### Troubleshooting sync

Check repository access, binding, and the project's sync mode before changing configuration. A failed authorization and a disabled mirror require different actions. Preserve recorded results and use the reported recovery rather than creating duplicate issues.

See [GitHub integration](../github/index.md), [Issue synchronization](../github/sync.md), and [Deployments and releases](delivery.md).
