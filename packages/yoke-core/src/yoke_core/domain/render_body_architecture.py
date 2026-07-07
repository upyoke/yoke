"""Architecture-impact body-section renderer.

Sibling of :mod:`render_body` so the parent module stays under the
350-line authored-file cap. Owns the formatting of the
``## Architecture Impact`` section, which surfaces the item's
:mod:`yoke_core.domain.architecture_impact` enum classification for
human review on the rendered body.

The section is emitted only when ``architecture_impact`` differs from
the readiness-passing default ``'none'``; ``none`` is the implicit
baseline and adds nothing to render.
"""

from __future__ import annotations

from typing import Optional


_IMPACT_DESCRIPTIONS = {
    "none": "no impact on the architecture model or path classification",
    "path_context_only": (
        "touches inherited path-context families "
        "(architecture_layer / architecture_domain / cross-cutting "
        "entrypoint assignments) but not the model payload"
    ),
    "architecture_model_change": (
        "modifies the project architecture model itself (domains, layers, "
        "allowed/forbidden edges, cross-cutting entrypoint registry, or "
        "exemption policy)"
    ),
    "uncertain": (
        "operator declared at idea time; refine / Architect must resolve "
        "before refined-idea"
    ),
}


def render_architecture_impact_section(
    architecture_impact: Optional[str],
) -> str:
    """Return the rendered section or '' when the value is empty / 'none'.

    Empty value or ``'none'`` (the readiness-passing default) emits no
    section; the absence is itself the affirmative signal.
    """
    if not architecture_impact:
        return ""
    value = str(architecture_impact).strip().lower()
    if not value or value == "none":
        return ""
    description = _IMPACT_DESCRIPTIONS.get(value, "")
    lines = ["## Architecture Impact", ""]
    if description:
        lines.append(f"- **Class:** `{value}` — {description}.")
    else:
        lines.append(f"- **Class:** `{value}`.")
    return "\n".join(lines)


__all__ = ["render_architecture_impact_section"]
