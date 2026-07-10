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
    AdapterEntry(function_id="auth.set.run", cli_invocation="yoke auth set ENV CREDENTIAL", notes="Machine-local credential rotation; direct credential is the default, with --token-file/--token-stdin/--dsn/--dsn-file/--dsn-stdin for scripted inputs."),
    AdapterEntry(function_id="project.register.run", cli_invocation="yoke project register REPO_ROOT --project-id N", notes="Machine-local checkout -> (env, project id) mapping."),
    AdapterEntry(function_id="config.stamp_project_env.run", cli_invocation="yoke config stamp-project-env", notes="Machine-local: stamps untagged projects entries with the selected connection env (default active_env)."),
    AdapterEntry(function_id="project.install.run", cli_invocation="yoke project install [REPO_ROOT] --project-id N", notes="Writes the project-local layer from the active env; manifest-tracked."),
    AdapterEntry(function_id="project.refresh.run", cli_invocation="yoke project refresh [REPO_ROOT]", notes="Same code path as install; prunes bundle-dropped files via the manifest."),
    AdapterEntry(function_id="project.uninstall.run", cli_invocation="yoke project uninstall [REPO_ROOT]", notes="Removes manifest-tracked files and de-merges Yoke hook entries."),
    AdapterEntry(function_id="project.snapshot.sync", cli_invocation="yoke project snapshot sync [REPO_ROOT] [--project P]", notes="Client scans committed git tree state; API writes canonical path snapshot rows for the project."),
    _read_entry(function_id="templates.list.run", cli_invocation="yoke templates list [--json]", notes="Discovers the templates the active env serves (name, description, file count)."),
    AdapterEntry(function_id="templates.fetch.run", cli_invocation="yoke templates fetch NAME [--dest DIR] [--only SUBPATH] [--force] [--source-dev-admin]", notes="Delivers one template's files raw (placeholders intact); source-dev/admin templates require explicit opt-in."),
    _read_entry(function_id="projects.capability.has", cli_invocation="python3 -m yoke_core.cli.db_router projects has-capability"),
    _read_entry(function_id="projects.get", cli_invocation="python3 -m yoke_core.cli.db_router projects get <project> [field]"),
    _read_entry(function_id="projects.resolve_by_github_repo", cli_invocation="yoke projects resolve-by-github-repo --github-repo OWNER/REPO"),
    AdapterEntry(function_id="projects.create", cli_invocation="yoke projects create --slug SLUG --name NAME [--project-id N]", notes="Register a new project (org-scoped, org admin). Idempotent: re-onboarding the same slug updates fields."),
    AdapterEntry(function_id="projects.update", cli_invocation="yoke projects update --slug SLUG --name NAME [--project-id N]", notes="Edit an existing project (project-scoped, that project's admin); errors if the project does not exist."),
    AdapterEntry(function_id="projects.capability_secret.set", cli_invocation="yoke projects capability secret set --project NAME --cap-type TYPE --key KEY VALUE", notes="Stores active non-GitHub capability secrets. GitHub secret writes are refused: existing rows are stranded non-authoritative data, repository access uses binding rows, and App private keys stay control-plane-only. aws-admin secrets and ssh.private_key are written to the local machine under ~/.yoke/secrets/capability-secrets. Direct VALUE is the default, with --value-file/--value-stdin for scripted inputs."),
    _read_entry(function_id="projects.checkout_context.run", cli_invocation="yoke projects checkout-context [--field id|slug|name|public_item_prefix]", notes="Checkout->project identity for skill preambles; the client resolves the machine-config mapping, the server enriches with the projects row."),
    _read_entry(function_id="onboard.checklist.init", cli_invocation="yoke onboard checklist init --config PATH [--checkout PATH] [--project-id N] [--json]", notes="Local checklist seed from machine config and checkout metadata; no secret values are emitted."),
]


__all__ = ["INSTALLER_ADAPTERS"]
