"""Package-root teaching in the agent context packet.

An agent that greps for a module by guessing a directory named after the
package finds nothing and concludes the code is missing. The packet ships
verbatim into every project Yoke installs into, so it teaches the lookup
and the vocabulary rather than any one project's paths; the concrete
mapping stays in the per-project ``architecture_model``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.architecture_model_sections import PACKAGE_LAYOUTS
from yoke_core.domain.schema_api_context_render import render_package_roots_block

BLOCK_HEADING = "**Package roots:**"


class TestRenderedBlock:
    """The block teaches the rule, the read, and both declared layouts."""

    @pytest.fixture
    def block(self) -> str:
        rendered = render_package_roots_block()
        assert len(rendered) == 1
        return rendered[0]

    def test_glosses_every_declared_layout(self, block: str):
        for layout in PACKAGE_LAYOUTS:
            assert f"`{layout}`" in block

class TestEveryRoleIsTaught:
    """`core` is the universal topic, so no role misses the lookup."""

    def test_core_topic_carries_the_block(self):
        assert BLOCK_HEADING in sac.render_topic_packet("core")

    def test_every_role_packet_carries_the_block(self):
        for role in seed.ROLE_TOPICS:
            assert BLOCK_HEADING in sac.render_role_packet(role), role
