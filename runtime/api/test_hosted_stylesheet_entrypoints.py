"""Published hosted-stylesheet contract and generated-document coverage."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
import shutil

from yoke_core.ui import asset_roster
from yoke_core.ui.hosted_stylesheet_entrypoints import (
    CONTRACT_REL,
    STATIC_REL,
    detect_drift,
    load_contract,
    stylesheet_reachability_gaps,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _isolated_bundle(tmp_path: Path) -> Path:
    contract_target = tmp_path / CONTRACT_REL
    contract_target.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / CONTRACT_REL, contract_target)
    shutil.copytree(REPO_ROOT / STATIC_REL, tmp_path / STATIC_REL)
    return tmp_path


def test_published_contract_owns_the_cascade_and_host_mapping():
    contract_path = files("yoke_core.ui").joinpath(
        "contracts", "hosted-stylesheets.json"
    )
    assert contract_path.is_file()
    contract = load_contract(Path(str(contract_path)))
    hosted_hrefs = contract.hosted_hrefs()
    assert hosted_hrefs[0].split("/")[1] == "brand"
    assert all(href.split("/")[1] == "universe" for href in hosted_hrefs[1:])
    assert tuple(Path(href).name for href in hosted_hrefs) == tuple(
        entry.asset for entry in contract.entrypoints
    )
    assert contract.entrypoints[-1].asset == "universe_responsive.css"


def test_raw_documents_are_generated_from_the_published_contract():
    assert detect_drift(target_root=REPO_ROOT) == []


def test_document_drift_is_detected(tmp_path):
    target_root = _isolated_bundle(tmp_path)
    index = target_root / STATIC_REL / "index.html"
    first_entrypoint = load_contract(target_root / CONTRACT_REL).entrypoints[0].asset
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            f'<link rel="stylesheet" href="./assets/{first_entrypoint}">', "", 1
        ),
        encoding="utf-8",
    )
    assert detect_drift(target_root=target_root) == ["index.html"]


def test_every_shipped_stylesheet_is_reachable(tmp_path):
    target_root = _isolated_bundle(tmp_path)
    assert stylesheet_reachability_gaps(target_root=target_root) == []
    orphan = target_root / STATIC_REL / "unlinked_stylesheet.css"
    orphan.write_text(".unlinked { display: block; }\n", encoding="utf-8")
    assert stylesheet_reachability_gaps(target_root=target_root) == [orphan.name]


def test_closed_asset_roster_matches_the_static_bundle():
    static_names = {
        path.name for path in (REPO_ROOT / STATIC_REL).iterdir() if path.is_file()
    }
    assert set(asset_roster.ASSET_CONTENT_TYPES) == static_names
