"""The latest Machine QA Pack teaches setup responsibility from one document."""

import json
from pathlib import Path

from yoke_core.domain import pack_catalog

ROOT = Path(__file__).resolve().parents[3]


def test_latest_pack_publishes_one_rule_and_links_every_provisioning_guide(monkeypatch):
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    descriptor = pack_catalog.load_pack_descriptor("machine-qa")
    version = descriptor["versions"][descriptor["latest_version"]]
    source = ROOT / "packs/machine-qa" / version["source"]
    rule_path = "docs/packs/machine-qa/setup-responsibilities.md"
    assert rule_path in {row["target"] for row in version["files"]}
    rule = (source / rule_path).read_text()
    assert "Agents do every setup step software can do" in rule
    assert "permission the OS refuses to let software grant" in rule
    assert "product code from stored secrets, never typed by hand" in rule
    guides = [
        source / "docs/packs/machine-qa" / name
        for name in (
            "host-provisioning.md",
            "macos-host-provisioning.md",
            "linux-host-provisioning.md",
            "windows-host-provisioning.md",
        )
    ]
    for guide in guides:
        text = guide.read_text()
        assert "(setup-responsibilities.md)" in text
        for obsolete in (
            "Every OS privacy/TCC consent dialog is an operator action",
            "Have the operator establish consent",
            "operator's interactive prompts",
            "typing passwords or credentials",
            "choosing or switching accounts",
        ):
            assert obsolete not in text
    # The historical baseline must remain reconstructible for three-way updates.
    historical = json.loads((ROOT / "packs/machine-qa/pack.json").read_text())[
        "versions"
    ]
    assert "1.3.11" in historical
