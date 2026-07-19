"""Product-boundary inventory for the installable ``yoke`` CLI.

The engine (yoke-core) is present on every machine; the active connection
decides whether it runs. Https connections relay every call to the server
and keep the engine inert; a non-prod local-postgres connection is a local
universe whose in-process dispatch is the product path; prod-flagged
postgres connections stay operator-only. Each row states the expected
behavior of a command/helper in a product install where the client packages
hold no static import authority over the engine and dispatch is
connection-gated.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from yoke_cli import operation_inventory as ops
from yoke_cli.commands.registry import SUBCOMMAND_ALIAS_REGISTRY, SUBCOMMAND_REGISTRY
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS
from yoke_cli.product_boundary_import_scan import (
    ImportEdge,
    load_boundary_facts,
    module_name_from_source,
    module_source,
    repo_root_from_package,
    scan_import_edges,
)
from yoke_cli.product_boundary_teaching import TeachingAudit, generate_teaching_audit
from yoke_cli.product_boundary_teaching_render import render_teaching_audit_markdown
PRODUCT_CLIENT = "product-client"
HTTPS_RELAY = "https-relay"
CLIENT_LOCAL_HELPER = "client-local helper"
SOURCE_DEV_ADMIN = "source-dev/admin"
HOOK_LOCAL_SUBSET = "hook-local subset"
OPERATOR_DEBUG_PERMANENT = "operator-debug permanent"
LEGACY_DELETE = "legacy/delete"
DISPOSITIONS = (PRODUCT_CLIENT, HTTPS_RELAY, CLIENT_LOCAL_HELPER, HOOK_LOCAL_SUBSET, SOURCE_DEV_ADMIN, OPERATOR_DEBUG_PERMANENT, LEGACY_DELETE)
def _commands(text: str) -> frozenset[str]:
    return frozenset(f"yoke {line}" for line in text.split("|") if line)

_PRODUCT = _commands("auth set|config example|connect|connection remove|connection set|core build|core logs|core start|core status|core stop|core upgrade|env use|github connect|github disconnect|github status|init|local-postgres start|local-postgres status|local-postgres stop|onboard|onboard checklist|onboard checklist init|onboard project|packs get|packs list|packs update|project create|project import|project install|project refresh|project register|project snapshot sync|project uninstall|self-host import|self-host init|status|ui|universe export|universe import|universe validate")
_PROJECT_INSTALL = _commands("project install|project refresh|project snapshot sync|project uninstall")
_SOURCE_DEV = _commands("agents render|agents render check|aws exec|board rebuild|dev setup|dev db-admin setup|dev path-snapshot-prewarm|github-actions runners status|merge audit|packets check|packets render|resync|runner-fleet exec|schema converge|scratch dispatch-inputs|source-authority export|source-authority quiesce|usher reconcile-github")
_HOOKS = _commands("git post-commit|git pre-commit|hook evaluate")
@dataclass(frozen=True)
class InventoryRow:
    command_helper: str; function_id: str | None; import_edges: tuple[ImportEdge, ...]  # noqa: E702
    transport_branch: str; config_required: str; capability_required: str  # noqa: E702
    expected_product_install_behavior: str; expected_refusal_shape: str  # noqa: E702
    owner: str; disposition: str  # noqa: E702

def generate_inventory(*, repo_root: Path | str | None = None, package_root: Path | str | None = None) -> tuple[InventoryRow, ...]:
    """Return deterministic product-boundary rows for this CLI build."""
    pkg = Path(package_root).resolve() if package_root else Path(__file__).resolve().parent
    root = Path(repo_root).resolve() if repo_root else repo_root_from_package(pkg)
    boundary_roots, allowlist = load_boundary_facts(root)
    edges = scan_import_edges(pkg, root, boundary_roots, allowlist)
    op_by_shell = ops.by_shell_form()
    rows: list[InventoryRow] = []
    represented: set[str] = set()
    seen: set[str] = set()
    registry_items = [*SUBCOMMAND_REGISTRY.items(), *SUBCOMMAND_ALIAS_REGISTRY.items()]
    for tokens, (function_id, adapter) in sorted(registry_items, key=lambda i: (" ".join(i[0]), i[1][0])):
        shell = _shell(tokens)
        source = module_source(adapter.__module__, pkg, root)
        represented.add(source)
        op = op_by_shell.get(shell)
        rows.append(_make_row(shell, function_id, edges.get(source, ()), op, _owner(shell, op, adapter.__module__)))
        seen.add(shell)
    for tokens, adapter in sorted(TOOL_SHAPED_SUBCOMMANDS.items(), key=lambda i: " ".join(i[0])):
        shell = _shell(tokens)
        source = module_source(adapter.__module__, pkg, root)
        represented.add(source)
        op = op_by_shell.get(shell)
        rows.append(_make_row(shell, None, edges.get(source, ()), op, _owner(shell, op, adapter.__module__)))
        seen.add(shell)
    for entry in ops.all_entries():
        if entry.shell_form not in seen:
            rows.append(_make_row(entry.shell_form, entry.proposed_function_id, (), entry, entry.family))
            seen.add(entry.shell_form)
    for source, source_edges in sorted(edges.items()):
        if source not in represented:
            module = module_name_from_source(source)
            rows.append(_make_row(f"helper {module}", None, source_edges, None, module))
    order = {name: index for index, name in enumerate(DISPOSITIONS)}
    return tuple(sorted(rows, key=lambda r: (order.get(r.disposition, len(order)), r.command_helper, r.function_id or "")))

def render_markdown(rows: Iterable[InventoryRow], *, teaching_audit: TeachingAudit | None = None) -> str:
    """Render a deterministic Markdown product-boundary report."""
    ordered = tuple(rows)
    lines = [
        "# Yoke CLI Product-Boundary Inventory",
        "",
        "Generated from `yoke_cli.commands.registry`, `yoke_cli.operation_inventory`, `yoke_cli.commands.tool_shaped`, and the package import-boundary scan.",
        "",
    ]
    header = "| command/helper | function_id | transport_branch | config_required | capability_required | product install | refusal shape | owner | import_edges |"
    for disposition in DISPOSITIONS:
        group = sorted((row for row in ordered if row.disposition == disposition), key=lambda r: r.command_helper)
        if not group:
            continue
        lines.extend([f"## {disposition}", "", header, "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"])
        lines.extend(_markdown_row(row) for row in group)
        lines.append("")
    if teaching_audit is not None:
        lines.extend(render_teaching_audit_markdown(teaching_audit))
    return "\n".join(lines).rstrip() + "\n"

def _make_row(command: str, function_id: str | None, edges: tuple[ImportEdge, ...], operation: ops.OperationEntry | None, owner: str) -> InventoryRow:
    disposition = _disposition(command, edges, operation)
    return InventoryRow(
        command_helper=command,
        function_id=function_id,
        import_edges=edges,
        transport_branch=_branch(command, disposition, operation),
        config_required=_config(command, disposition),
        capability_required=_capability(command, disposition),
        expected_product_install_behavior=_product_install(disposition),
        expected_refusal_shape=_refusal(command, disposition, operation),
        owner=owner,
        disposition=disposition,
    )

def _disposition(command: str, edges: Sequence[ImportEdge], operation: ops.OperationEntry | None) -> str:
    classes = {edge.classification for edge in edges}
    if command in _HOOKS:
        return HOOK_LOCAL_SUBSET
    if command in _SOURCE_DEV:
        return SOURCE_DEV_ADMIN
    if classes & {"project_layer_writer", "static_authority_import"}:
        return LEGACY_DELETE
    if command in _PRODUCT:
        return PRODUCT_CLIENT
    if operation and operation.status == ops.PENDING:
        return LEGACY_DELETE
    if operation and operation.status == ops.PERMANENT:
        return OPERATOR_DEBUG_PERMANENT if operation.reason == ops.REASON_OPERATOR_BREAK_GLASS else CLIENT_LOCAL_HELPER
    if classes & {"source_dev_admin", "unclassified_dynamic_authority_import"}:
        return SOURCE_DEV_ADMIN
    # local_universe_dispatch edges are product-path (in-process dispatch on
    # a non-prod local universe); rows carrying them keep their command or
    # helper disposition instead of demoting to source-dev/admin.
    if "client_local_harness_adapter" in classes:
        return HOOK_LOCAL_SUBSET
    return CLIENT_LOCAL_HELPER if command.startswith("helper ") else HTTPS_RELAY

def _branch(command: str, disposition: str, operation: ops.OperationEntry | None) -> str:
    if command in _PROJECT_INSTALL:
        return "project-install-https-bundle"
    if command == "yoke dev db-admin setup":
        return "named-https-control-plane-read-plus-source-dev-admin-local"
    by_disposition = {
        PRODUCT_CLIENT: "product-client-local",
        HTTPS_RELAY: "https-relay",
        HOOK_LOCAL_SUBSET: "hook-local-or-https-relay",
        SOURCE_DEV_ADMIN: "source-dev-admin-local",
        OPERATOR_DEBUG_PERMANENT: "operator-debug-command",
        LEGACY_DELETE: "legacy-command-shaped",
    }
    if disposition in by_disposition:
        return by_disposition[disposition]
    return "client-local-tool" if operation and operation.reason == ops.REASON_TOOL_SHAPED else "client-local-helper"

def _config(command: str, disposition: str) -> str:
    by_command = {
        "yoke github connect": "machine config path and GitHub App authorization source", "yoke github disconnect": "machine config path and local authorization removal",
        "yoke onboard": "target config path, env, API URL, GitHub App authorization, optional local checkout handoff inputs",
        "yoke dev setup": "Yoke source checkout; optional local-postgres DSN inputs",
        "yoke dev db-admin setup": (
            "named HTTPS control-plane env plus project/env deploy settings"
        ),
        "yoke aws exec": "project aws-admin capability settings plus local AWS CLI",
        "yoke runner-fleet exec": (
            "versioned project stack-config snapshot plus child command"
        ),
    }
    if command in _PROJECT_INSTALL:
        return "machine config HTTPS env plus project id or checkout mapping"
    if command in by_command: return by_command[command]  # noqa: E701
    return {
        HTTPS_RELAY: "active env machine config; HTTPS preferred",
        SOURCE_DEV_ADMIN: "source checkout/admin runtime",
        OPERATOR_DEBUG_PERMANENT: "operator-selected source-dev/admin shell",
        HOOK_LOCAL_SUBSET: "hook event payload; HTTPS env optional for server half",
    }.get(disposition, "machine-local config as requested by the helper")

def _capability(command: str, disposition: str) -> str:
    if command.startswith("yoke github pr ") or command.startswith("yoke github-actions "):
        return "project GitHub App auth"
    if command in _PROJECT_INSTALL:
        return "project install bundle endpoint"
    if command == "yoke dev setup": return "yoke-core source package for apply/source-link repair"  # noqa: E701
    if command == "yoke dev db-admin setup": return "named HTTPS db.read.run plus project aws-admin, pulumi-state, ssh, database, and runtime settings"  # noqa: E701
    if command == "yoke aws exec": return "project aws-admin capability credentials"  # noqa: E701
    if command == "yoke runner-fleet exec": return "project aws-admin plus repository-bound GitHub App authority"  # noqa: E701
    if disposition == HTTPS_RELAY:
        return "server-registered function id"
    if disposition == OPERATOR_DEBUG_PERMANENT:
        return "operator break-glass authority"
    return "none"

def _product_install(disposition: str) -> str:
    return {
        PRODUCT_CLIENT: "supported in a product install; engine stays inert",
        HTTPS_RELAY: "supported via HTTPS relay or in-process on a non-prod local universe",
        CLIENT_LOCAL_HELPER: "supported when local helper dependencies are present",
        HOOK_LOCAL_SUBSET: "supported for installed hook relay/local subset",
        SOURCE_DEV_ADMIN: "outside normal product lane; requires source-dev/admin setup",
        OPERATOR_DEBUG_PERMANENT: "not a product CLI surface; command-shaped operator boundary",
        LEGACY_DELETE: "legacy boundary; replace with product or delete",
    }[disposition]

def _refusal(command: str, disposition: str, operation: ops.OperationEntry | None) -> str:
    if command == "yoke status":
        return "machine-config issue report; no yoke-core import"
    if command.startswith("yoke core "):
        return "typed Docker/Colima/local-core guidance; no yoke-core import"
    if command == "yoke dev db-admin setup":
        return "fail-closed named-HTTPS binding or exact database-identity error"
    if disposition == HTTPS_RELAY:
        return "FunctionCallResponse error envelope"
    if disposition == HOOK_LOCAL_SUBSET:
        return "hook no-op degrade on HTTPS failure; argparse errors otherwise"
    if disposition == SOURCE_DEV_ADMIN:
        return "source-dev/admin command error or wrapped ModuleNotFoundError"
    if disposition == OPERATOR_DEBUG_PERMANENT:
        reason = operation.reason if operation else "operator boundary"
        return f"explicit non-product command remains {reason}"
    if disposition == LEGACY_DELETE:
        return "no clean product behavior; migrate or remove"
    return "argparse or helper-specific product error"

def _owner(shell_form: str, operation: ops.OperationEntry | None, module: str) -> str:
    return operation.family if operation else module if shell_form.startswith("yoke ") else "source-dev/admin"

def _shell(tokens: Sequence[str]) -> str:
    return "yoke " + " ".join(tokens)

def _edge_text(edges: Sequence[ImportEdge]) -> str:
    return "none" if not edges else "<br>".join(f"{e.kind}:{e.source}->{e.target} [{e.classification}]" for e in edges)

def _markdown_row(row: InventoryRow) -> str:
    values = (
        row.command_helper, row.function_id or "", row.transport_branch,
        row.config_required, row.capability_required,
        row.expected_product_install_behavior, row.expected_refusal_shape,
        row.owner, _edge_text(row.import_edges),
    )
    return "| " + " | ".join(_md(value) for value in values) + " |"

def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")

__all__ = ["CLIENT_LOCAL_HELPER", "DISPOSITIONS", "HOOK_LOCAL_SUBSET", "HTTPS_RELAY", "ImportEdge", "InventoryRow", "LEGACY_DELETE", "OPERATOR_DEBUG_PERMANENT", "PRODUCT_CLIENT", "SOURCE_DEV_ADMIN", "generate_inventory", "generate_teaching_audit", "render_markdown"]
