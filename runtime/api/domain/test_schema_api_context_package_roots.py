"""Package-root teaching in the agent context packet.

An agent that greps for a module by guessing a repo-root directory named
after the package finds nothing and concludes the code is missing. These
tests pin the three properties that prevent it: every role is taught the
roots, the values come from the resolver rather than prose, and a seed
that disagrees with the project's declared model reports drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.schema_api_context_package_roots import (
    LAYOUT_GLOSS,
    describe_drift,
)
from yoke_core.domain.schema_api_context_render import render_package_roots_block

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestRenderedBlock:
    """The rendered block names every declared root and layout."""

    def test_renders_each_package_and_root(self):
        block = render_package_roots_block(
            {"pkg_one": (("some/root", "package_under_root"),)}
        )
        assert len(block) == 1
        assert "`pkg_one`" in block[0]
        assert "`some/root` (package_under_root)" in block[0]
        assert LAYOUT_GLOSS["package_under_root"] in block[0]

    def test_renders_both_roots_of_a_dual_root_package(self):
        block = render_package_roots_block(
            {
                "pkg_two": (
                    ("under/root", "package_under_root"),
                    ("is/root", "package_is_root"),
                ),
            }
        )
        assert "`under/root` (package_under_root)" in block[0]
        assert "`is/root` (package_is_root)" in block[0]

    def test_renders_nothing_without_declared_roots(self):
        assert render_package_roots_block({}) == []


class TestCoreTopic:
    """Every role inherits `core`, so every role is taught the roots."""

    @pytest.fixture
    def core_packet(self) -> str:
        return sac.render_topic_packet("core")

    def test_core_topic_carries_the_block(self, core_packet: str):
        assert "**Package roots (where a module actually lives):**" in core_packet

    def test_every_role_packet_carries_the_block(self):
        for role in seed.ROLE_TOPICS:
            body = sac.render_role_packet(role)
            assert "**Package roots (where a module actually lives):**" in body, role

    def test_seeded_roots_appear_in_the_rendered_core_topic(self, core_packet: str):
        for package, entries in seed.PACKAGE_ROOTS.items():
            assert f"`{package}`" in core_packet
            for root, layout in entries:
                assert f"`{root}` ({layout})" in core_packet


class TestSeedMatchesRepository:
    """The seeded roots describe directories that actually exist."""

    def test_every_seeded_root_exists_in_the_repo(self):
        for package, entries in seed.PACKAGE_ROOTS.items():
            for root, layout in entries:
                resolved = REPO_ROOT / root
                assert resolved.is_dir(), f"{package}: missing root {root}"
                if layout == "package_under_root":
                    assert (resolved / package).is_dir(), (
                        f"{package}: {root} declares package_under_root but "
                        f"holds no {package} directory"
                    )

    def test_every_seeded_layout_has_a_gloss(self):
        for entries in seed.PACKAGE_ROOTS.values():
            for _root, layout in entries:
                assert layout in LAYOUT_GLOSS


class TestDriftAgainstModel:
    """Divergence from the declared model is reported, never rendered."""

    def test_matching_declarations_report_no_drift(self):
        roots = {"pkg": (("a/b", "package_under_root"),)}
        assert describe_drift(seed_roots=roots, live_roots=dict(roots)) == []

    def test_changed_root_reports_drift(self):
        drift = describe_drift(
            seed_roots={"pkg": (("a/b", "package_under_root"),)},
            live_roots={"pkg": (("a/c", "package_under_root"),)},
        )
        assert len(drift) == 1
        assert "a/b" in drift[0] and "a/c" in drift[0]

    def test_package_only_in_the_model_reports_drift(self):
        drift = describe_drift(
            seed_roots={},
            live_roots={"pkg": (("a/b", "package_under_root"),)},
        )
        assert "the packet seed has no such package" in drift[0]

    def test_package_only_in_the_seed_reports_drift(self):
        drift = describe_drift(
            seed_roots={"pkg": (("a/b", "package_under_root"),)},
            live_roots={"other": (("c/d", "package_is_root"),)},
        )
        assert any("has no such package" in entry for entry in drift)
        assert any("packet seed has no such package" in entry for entry in drift)
