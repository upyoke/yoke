"""Doc regressions for verification-failure ownership and path-claim override discipline."""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()


def _read(rel_path: str) -> str:
    return (REPO / rel_path).read_text(encoding="utf-8")


def test_verification_home_defines_current_item_verification_ownership():
    text = _read("docs/public/agents/rules/verification.md")

    assert "## Verification failure ownership" in text
    assert "Current-item verification failures belong to the current item" in text
    assert "planned path claim is not a waiver" in text
    assert "Use dependency and claim reconciliation before override" in text
    assert "Do not use `path-claim-override` for a planned future claim" in text
    assert "requires a live steering seat covering the project" in text


def test_installed_verification_home_carries_claim_override_policy():
    home = _read(".yoke/docs/agents/rules/verification.md")
    assert "planned path claim" in home
    assert "Use dependency and claim reconciliation before override" in home
    assert "Do not use `path-claim-override` for a planned future claim" in home
    assert "override is last resort" in home
    assert "requires a live steering seat covering the project" in home


def test_unchanged_consumer_test_failure_routes_to_the_producer():
    bundle = "packages/yoke-core/src/yoke_core/install_bundle_tree/"
    rule_homes = [
        "docs/public/agents/rules/verification.md",
        f"{bundle}docs/public/agents/rules/verification.md",
        ".yoke/docs/agents/rules/verification.md",
    ]
    for rel_path in rule_homes:
        text = " ".join(_read(rel_path).split())
        assert (
            "A consumer test this item did not change that fails against a new "
            "producer source is evidence against the producer" in text
        ), rel_path
        assert "producer commit range or item" in text, rel_path
        assert "producer's companion item" in text, rel_path

    for rel_path in ("AGENTS.md", f"{bundle}AGENTS.md"):
        text = " ".join(_read(rel_path).split())
        assert "A verification failure in this item belongs to this item" in text, (
            rel_path
        )
        assert (
            "Never edit or weaken an unchanged consumer test that fails against new "
            "producer code; route it to the producer"
        ) in text, rel_path
