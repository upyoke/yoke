"""Every placeholder a shipped stack template carries must be renderable.

A stack template and the key set that fills it are authored in different
places, and nothing forces them to agree. When they disagree the placeholder
survives substitution verbatim, Pulumi rejects the resulting YAML, and the
stack cannot be previewed or applied at all — the registry template shipped in
exactly that state, carrying a delivery-authority placeholder the registry key
set omitted.

The reason a template-rendering test did not catch it is worth keeping in
view: one already renders the real registry template and already asserts that
no ``{{`` survives, but it hand-authors the values it renders with, so it
supplies the missing key itself and passes against a key set that would drop
it. An expectation restated by hand cannot detect that the thing it restates
has drifted.

So these tests derive both sides from the artifacts. The placeholders come out
of the shipped template, the selection comes from the same function the render
path uses, and neither is written down here.
"""

from __future__ import annotations

import re

import pytest

from yoke_core.domain.project_renderer_pulumi_stack_config import (
    _selected_render_values,
)
from yoke_core.domain.project_renderer_pulumi_stack_types import STACK_TYPE_SPECS
from runtime.api.domain.webapp_pulumi_test_support import _pack_program_source

#: ``{{ name }}`` as the stack templates write it.
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

#: The environment kind renders through the scoped config path rather than the
#: declared stack-type registry, so its template is named here to keep it under
#: the same rule. Only the artifact is named; its keys are still derived.
_SCOPED_KIND_TEMPLATES = (("environment", "Pulumi.environment-stack.yaml.tmpl"),)

_KIND_TEMPLATES = sorted(
    {
        *((kind, template) for kind, (_, template) in STACK_TYPE_SPECS.items()),
        *_SCOPED_KIND_TEMPLATES,
    }
)


def _placeholders(template: str) -> set[str]:
    return set(_PLACEHOLDER.findall(template))


@pytest.mark.parametrize("kind,template_name", _KIND_TEMPLATES, ids=lambda v: str(v))
def test_every_template_placeholder_is_renderable_for_its_kind(
    kind: str, template_name: str
) -> None:
    """A placeholder the key set drops renders as literal ``{{ }}``."""
    template = _pack_program_source(template_name).read_text()
    placeholders = _placeholders(template)
    assert placeholders, f"{template_name} carries no placeholders to check"

    # Offer the selection every name the template asks for. Whatever it does
    # not hand back is a placeholder the render path cannot fill.
    selected = _selected_render_values(kind, {name: "x" for name in placeholders})

    dropped = placeholders - set(selected)
    assert not dropped, (
        f"{template_name} renders {sorted(dropped)} for stack kind {kind!r}, "
        "but the render path drops those keys; they would survive substitution "
        "as literal {{ }} and Pulumi would reject the stack config"
    )


def test_a_template_placeholder_with_no_key_is_caught() -> None:
    """The check above fails when a template asks for something unfillable.

    Without this, a selection that silently returned its whole input would
    make every case above pass while catching nothing.
    """
    placeholders = _placeholders("webapp-infra:absent: {{ nothing_supplies_this }}")

    selected = _selected_render_values(
        "registry", {name: "x" for name in placeholders}
    )

    assert placeholders - set(selected) == {"nothing_supplies_this"}
