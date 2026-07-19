"""Installer, machine-config, and project capability CLI adapter entries."""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


INSTALLER_ADAPTERS: List[AdapterEntry] = [
    _read_entry(function_id="config.example.run", cli_invocation="yoke config example", notes="Prints the code-owned canonical machine config example."),
    _read_entry(function_id="status.run", cli_invocation="yoke status [--json]", notes="Reports machine config, resolver, board, and runtime health."),
    AdapterEntry(function_id="env.use.run", cli_invocation="yoke env use ENV", notes="Machine-local: flips active_env in ~/.yoke/config.json."),
    AdapterEntry(function_id="connection.set.run", cli_invocation="yoke connection set ENV [CREDENTIAL|DSN] [...]", notes="Machine-local connection update; direct credential/DSN is the default and secrets land in ~/.yoke/secrets."),
    AdapterEntry(function_id="connection.remove.run", cli_invocation="yoke connection remove ENV", notes="Owner-only inactive alias retirement with Yoke-owned credential cleanup; active authority and non-owned secret paths are refused."),
    AdapterEntry(function_id="auth.set.run", cli_invocation="yoke auth set ENV CREDENTIAL", notes="Machine-local credential rotation; direct credential is the default, with --token-file/--token-stdin/--dsn/--dsn-file/--dsn-stdin for scripted inputs."),
    AdapterEntry(function_id="project.register.run", cli_invocation="yoke project register REPO_ROOT --project-id N", notes="Machine-local checkout -> (env, project id) mapping."),
    AdapterEntry(function_id="config.stamp_project_env.run", cli_invocation="yoke config stamp-project-env", notes="Machine-local: stamps untagged projects entries with the selected connection env (default active_env)."),
    AdapterEntry(function_id="project.install.run", cli_invocation="yoke project install [REPO_ROOT] --project-id N", notes="Writes the project-local layer from the active env; manifest-tracked."),
    AdapterEntry(function_id="project.refresh.run", cli_invocation="yoke project refresh [REPO_ROOT]", notes="Same code path as install; prunes bundle-dropped files via the manifest."),
    AdapterEntry(function_id="project.uninstall.run", cli_invocation="yoke project uninstall [REPO_ROOT]", notes="Removes manifest-tracked files and de-merges Yoke hook entries."),
    AdapterEntry(function_id="project.snapshot.sync", cli_invocation="yoke project snapshot sync [REPO_ROOT] [--project P]", notes="Client scans committed git tree state; API writes canonical path snapshot rows for the project."),
    _read_entry(function_id="packs.list", cli_invocation="yoke packs list --project NAME [--json]", notes="Shows available, installed, and stale Packs from the shipped catalog plus the project's last repository report."),
    _read_entry(function_id="packs.bundle.get", cli_invocation="yoke packs get PACK [REPO_ROOT] --project NAME", notes="Returns one immutable, project-rendered Pack bundle; the client previews local checkout conflicts before any write."),
    AdapterEntry(function_id="packs.project.report", cli_invocation="yoke packs get|update PACK [REPO_ROOT] --project NAME --apply", notes="Refreshes the non-authoritative DB projection only after the project receipt is written."),
    AdapterEntry(function_id="packs.get.run", cli_invocation="yoke packs get PACK [REPO_ROOT] --project NAME [--apply]", notes="Client-local preview/apply boundary. Installs the selected Pack and missing dependencies, then writes the project-owned receipt."),
    AdapterEntry(function_id="packs.update.run", cli_invocation="yoke packs update PACK [REPO_ROOT] --project NAME [--apply]", notes="Client-local three-way update against the old immutable Pack, the new version, and the customized checkout; it never prunes project-owned files."),
    _read_entry(function_id="projects.capability.has", cli_invocation="python3 -m yoke_core.cli.db_router projects has-capability"),
    _read_entry(function_id="projects.capability_settings.get", cli_invocation="yoke projects capability-settings get --project NAME --cap-type TYPE", notes="Reads non-sensitive settings over the active transport; the exact returned JSON is the CAS base token. Capability listings may include pulumi-state, but its settings read is stack-scoped and must use yoke projects pulumi-stack-config get."),
    AdapterEntry(function_id="projects.capability_settings.set", cli_invocation="yoke projects capability-settings set --project NAME --cap-type TYPE --settings-json JSON (--base AS_READ_JSON | --new)", notes="Lost-update-protected full create/replace. Typed capabilities validate and canonicalize before mutation; GitHub full writes remain binding-owned and refused."),
    AdapterEntry(function_id="projects.capability_settings.merge", cli_invocation="yoke projects capability-settings merge --project NAME --cap-type TYPE --set KEY.PATH=VALUE", notes="Server-side read-merge-CAS composition with one conflict retry. Typed capability validation runs on the merged document."),
    _read_entry(function_id="projects.environment_settings.get", cli_invocation="yoke projects environment-settings get --project NAME --environment-id ID", notes="Reads one project-owned environment settings document over the active transport."),
    AdapterEntry(function_id="projects.environment_settings.merge", cli_invocation="yoke projects environment-settings merge --project NAME --environment-id ID --set KEY.PATH=VALUE", notes="Server-side read-merge-CAS composition with project/environment ownership verification."),
    AdapterEntry(function_id="projects.pulumi_state.migrate", cli_invocation="yoke projects pulumi-state migrate --project NAME --site-id ID --stack NAME [--apply]", notes="Dry-run-default exact-set transactional move with a metadata-only receipt; sensitive Pulumi operator-state values never cross the function boundary."),
    AdapterEntry(function_id="projects.pulumi_state.checkpoint_import", cli_invocation="yoke projects pulumi-state checkpoint-import --project NAME --stack NAME --checkpoint-file PATH [--apply]", notes="Reads one owner-only Pulumi checkpoint locally and registers only its typed encrypted operator-state entry. Dry-run-default, conflict-refusing, and redacted on every output surface."),
    _read_entry(function_id="projects.pulumi_stack_config.get", cli_invocation="yoke projects pulumi-stack-config get --project NAME --stack STACK --output FILE", notes="The registered result is an admin authorization receipt with no operator state; the CLI fetches the schema-v2 body through the dedicated no-store boundary, writes a new 0600 file, and emits only path, byte count, and digest."),
    _read_entry(function_id="projects.get", cli_invocation="python3 -m yoke_core.cli.db_router projects get <project> [field]"),
    _read_entry(function_id="projects.resolve_by_github_repo", cli_invocation="yoke projects resolve-by-github-repo --github-repo OWNER/REPO"),
    AdapterEntry(function_id="projects.create", cli_invocation="yoke projects create --slug SLUG --name NAME [--project-id N]", notes="Register a new project (org-scoped, org admin). New rows default to backlog-only; idempotent re-onboarding updates fields without resetting an omitted sync mode."),
    AdapterEntry(function_id="projects.update", cli_invocation="yoke projects update --slug SLUG --name NAME [--project-id N]", notes="Edit an existing project (project-scoped, that project's admin); errors if the project does not exist, and enabling issue sync requires an active verified App binding."),
    AdapterEntry(function_id="projects.capability_secret.set", cli_invocation="yoke projects capability secret set --project NAME --cap-type TYPE --key KEY VALUE", notes="Stores active non-GitHub capability secrets. GitHub capability-secret reads and writes are refused, repository access uses binding rows, and App private keys stay control-plane-only. aws-admin secrets and ssh.private_key are written to the local machine under ~/.yoke/secrets/capability-secrets. Direct VALUE is the default, with --value-file/--value-stdin for scripted inputs."),
    _read_entry(function_id="projects.checkout_context.run", cli_invocation="yoke projects checkout-context [--field id|slug|name|public_item_prefix]", notes="Checkout->project identity for skill preambles; the client resolves the machine-config mapping, the server enriches with the projects row."),
    _read_entry(function_id="onboard.checklist.init", cli_invocation="yoke onboard checklist init --config PATH [--checkout PATH] [--project-id N] [--json]", notes="Local checklist seed from machine config and checkout metadata; no secret values are emitted."),
]


__all__ = ["INSTALLER_ADAPTERS"]
