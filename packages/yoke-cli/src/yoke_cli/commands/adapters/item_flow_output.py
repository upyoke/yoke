"""Human item projections and effective flow provenance."""

from typing import Any
from yoke_contracts.read_detail import excerpt


def render_item_instruction_summary(instructions: list[dict[str, Any]], item: str) -> str:
    """Name applicable rules and the existing read that prints their full text."""
    if not instructions:
        return ""
    names = ", ".join(str(rule.get("id") or "operator rule") for rule in instructions)
    return f"Execution instructions {names} apply; full text: `yoke items get {item} --json`.\n"


def compact_item_result(result: dict[str, Any], item: str) -> dict[str, Any]:
    """Omit empty human fields and describe instructions already delivered as prose."""
    projected = dict(result)
    projected["fields"] = {
        key: value for key, value in (result.get("fields") or {}).items()
        if value is not None and value != ""
    }
    projected["sections"] = [
        section for section in result.get("sections", [])
        if str(section.get("content") or "").strip()
    ]
    projected["execution_instructions"] = [
        {
            **{key: value for key, value in instruction.items() if key != "content"},
            "title": excerpt(instruction.get("content")),
            "content_characters": len(str(instruction.get("content") or "")),
            "read": f"yoke items get {item} --json",
        }
        for instruction in result.get("execution_instructions") or []
    ]
    return projected


def render_item_field(value: Any) -> str:
    if isinstance(value, dict) and "value" in value and "source" in value:
        source = str(value["source"]).replace("_", " ")
        if value.get("pinned"):
            source += f"; follows retired pin {value['pinned']}"
        return f"{value['value'] or 'no completion flow'} ({source})"
    return "" if value is None else str(value)
