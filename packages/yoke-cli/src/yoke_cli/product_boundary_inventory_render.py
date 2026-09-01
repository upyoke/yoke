"""Markdown rendering for the generated product-boundary inventory."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from yoke_cli.product_boundary_import_scan import ImportEdge
from yoke_cli.product_boundary_teaching import TeachingAudit
from yoke_cli.product_boundary_teaching_render import render_teaching_audit_markdown


@dataclass(frozen=True)
class InventoryRow:
    command_helper: str
    function_id: str | None
    import_edges: tuple[ImportEdge, ...]  # noqa: E702
    transport_branch: str
    config_required: str
    capability_required: str  # noqa: E702
    expected_product_install_behavior: str
    expected_refusal_shape: str  # noqa: E702
    owner: str
    disposition: str  # noqa: E702


def render_inventory_markdown(
    rows: Iterable[InventoryRow],
    *,
    dispositions: Sequence[str],
    teaching_audit: TeachingAudit | None = None,
) -> str:
    """Render a deterministic Markdown product-boundary report."""
    ordered = tuple(rows)
    lines = [
        "# Yoke CLI Product-Boundary Inventory",
        "",
        "Generated from `yoke_cli.commands.registry`, `yoke_cli.operation_inventory`, `yoke_cli.commands.tool_shaped`, and the package import-boundary scan.",
        "",
    ]
    header = "| command/helper | function_id | transport_branch | config_required | capability_required | product install | refusal shape | owner | import_edges |"
    for disposition in dispositions:
        group = sorted(
            (row for row in ordered if row.disposition == disposition),
            key=lambda row: row.command_helper,
        )
        if not group:
            continue
        lines.extend(
            [
                f"## {disposition}",
                "",
                header,
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        lines.extend(_markdown_row(row) for row in group)
        lines.append("")
    if teaching_audit is not None:
        lines.extend(render_teaching_audit_markdown(teaching_audit))
    return "\n".join(lines).rstrip() + "\n"


def _markdown_row(row: InventoryRow) -> str:
    values = (
        row.command_helper,
        row.function_id or "",
        row.transport_branch,
        row.config_required,
        row.capability_required,
        row.expected_product_install_behavior,
        row.expected_refusal_shape,
        row.owner,
        _edge_text(row.import_edges),
    )
    return "| " + " | ".join(_markdown_cell(value) for value in values) + " |"


def _edge_text(edges: Sequence[ImportEdge]) -> str:
    if not edges:
        return "none"
    return "<br>".join(
        f"{edge.kind}:{edge.source}->{edge.target} [{edge.classification}]"
        for edge in edges
    )


def _markdown_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


__all__ = ["InventoryRow", "render_inventory_markdown"]
