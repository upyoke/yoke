"""Execute the published Pack templates as an installed standalone project."""

from importlib.resources import files
import json
import subprocess
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_structured_events_published_contract(tmp_path):
    descriptor = json.loads((ROOT / "packs/structured-events/pack.json").read_text())
    version = descriptor["versions"][descriptor["latest_version"]]
    source = ROOT / "packs/structured-events" / version["source"]
    for suffix in ("py", "mjs"):
        assert (
            source / "events" / f"events_timestamps.{suffix}"
        ).read_bytes() == files("yoke_contracts").joinpath(
            f"timestamps.{suffix}"
        ).read_bytes()
    for entry in version["files"]:
        target = tmp_path / entry["target"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            (source / entry["source"])
            .read_text()
            .replace("{{project_name}}", "example")
        )
    assert not list(tmp_path.rglob("*attribution_session*"))
    # The TypeScript collector imports Bowser; the ui package pins it for tests.
    modules = ROOT / "packages/yoke-core/src/yoke_core/ui/node_modules"
    assert (modules / "bowser").is_dir(), (
        "bowser_missing: run npm ci --prefix packages/yoke-core/src/yoke_core/ui"
    )
    (tmp_path / "node_modules").symlink_to(modules)
    for command in (
        [sys.executable, "-m", "pytest", "events", "-q"],
        ["node", "--experimental-strip-types", "--test", "events/test_browser.mjs"],
    ):
        result = subprocess.run(
            command, cwd=tmp_path, text=True, capture_output=True, timeout=45
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_current_standalone_collector_clock_properties(tmp_path):
    shutil.copytree(ROOT / "events", tmp_path / "events")
    modules = ROOT / "packages/yoke-core/src/yoke_core/ui/node_modules"
    (tmp_path / "node_modules").symlink_to(modules)
    result = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--test",
            "events/test_browser.mjs",
            "events/test_collector_instants.mjs",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
