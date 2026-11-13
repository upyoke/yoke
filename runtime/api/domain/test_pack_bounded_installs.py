"""Published Pack successors render and fail loudly on bounded outside installs."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import yaml

from yoke_core.domain import pack_catalog
from runtime.api.domain.pack_bounded_install_helpers import ROOT, run_fragment, shell_functions

VERSIONS = {
    "webapp-scaffold": ("1.1.7", "1.1.8"),
    "smoke-testing": ("1.1.1", "1.1.2"),
}


def bundle(monkeypatch, pack, version=None):
    descriptor = pack_catalog.load_pack_descriptor(pack, ROOT / "packs")
    selected = version or descriptor["latest_version"]
    keys = descriptor["versions"][selected]["settings_schema"]["required"]
    values = dict.fromkeys(keys, "sample")
    values.update({k: v for k, v in {
        "api_port": "8000", "web_port": "3000",
    }.items() if k in keys})
    monkeypatch.setattr(pack_catalog, "resolve_project",
                        lambda *a, **kw: SimpleNamespace(id=9, slug="sample"))
    return pack_catalog.build_pack_bundle(
        object(), project="sample", pack=pack, version=selected,
        render_values=values, packs_dir=ROOT / "packs",
    )


@pytest.mark.parametrize("pack", VERSIONS)
def test_successor_renders_complete_version_and_job_bounds(monkeypatch, pack):
    old, new = VERSIONS[pack]
    rendered = bundle(monkeypatch, pack)
    assert rendered["version"] == new
    previous = bundle(monkeypatch, pack, old)
    assert {f["path"] for f in previous["files"]} <= {
        f["path"] for f in rendered["files"]
    }
    descriptor = json.loads((ROOT / "packs" / pack / "pack.json").read_text())
    record = descriptor["versions"][new]
    source = ROOT / "packs" / pack / record["source"]
    assert {f["source"] for f in record["files"]} == {
        p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    }
    for row in rendered["files"]:
        if row["path"].endswith(".yml"):
            workflow = yaml.safe_load(row["content"])
            for job in workflow.get("jobs", {}).values():
                if "runs-on" in job:
                    assert 0 < job["timeout-minutes"] <= 60


def assert_outcomes(tmp_path, script, reason):
    for mode in ["success", "unreachable", "hung"]:
        result, calls = run_fragment(tmp_path, script, mode)
        if mode == "success":
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode != 0
            assert reason in result.stderr, result.stderr
            assert "re-run" in result.stderr
        assert "timeout" in calls


def test_rendered_workflow_install_steps_bound_failure(monkeypatch, tmp_path):
    scripts = []
    for row in bundle(monkeypatch, "webapp-scaffold")["files"]:
        if not row["path"].endswith(".yml"):
            continue
        for job in yaml.safe_load(row["content"]).get("jobs", {}).values():
            for step in job.get("steps", []):
                script = step.get("run", "")
                if any(x in script for x in ["pip install", "npm ci", "apt_get update",
                                             "playwright install-deps"]):
                    scripts.append(script)
    assert len(scripts) == 5
    for script in scripts:
        if "playwright install-deps" in script:
            # Avoid writing /etc on the test host. Inspect the actual apt
            # configuration and exercise both independent install commands.
            assert 'Acquire::Retries "3"' in script
            assert 'Acquire::http::Timeout "30"' in script
            script = "\n".join(line for line in script.splitlines()
                               if "sudo mkdir" not in line and "sudo tee" not in line)
        if "apt_get" in script:
            assert "Acquire::Retries=3" in script
            assert "APT::Update::Error-Mode=any" in script
        if "pip install" in script:
            assert "--retries 3 --timeout 30" in script
        if "npm ci" in script:
            assert "--fetch-retries=3 --fetch-timeout=30000" in script
        reason = ("pip_install_failed" if "pip install" in script else
                  "npm_install_failed" if "npm ci" in script else "apt_")
        assert_outcomes(tmp_path, script, reason)
        if "playwright install chromium" in script:
            browser = script[script.index("timeout --kill-after=10 600 env"):]
            assert_outcomes(tmp_path, shell_functions(script) + browser,
                            "playwright_download_failed")


def test_npm_zero_exit_incomplete_install_fails(monkeypatch, tmp_path):
    """npm10 may exit zero after ENOTFOUND while leaving direct deps missing."""
    scripts = []
    for row in bundle(monkeypatch, "webapp-scaffold")["files"]:
        if row["path"].endswith("ci.yml"):
            for job in yaml.safe_load(row["content"])["jobs"].values():
                scripts.extend(step["run"] for step in job["steps"]
                               if "npm ci" in step.get("run", ""))
    assert len(scripts) == 2
    for script in scripts:
        result, calls = run_fragment(tmp_path, script, "incomplete")
        assert result.returncode != 0
        assert "npm_install_failed" in result.stderr
        assert "re-run" in result.stderr
        assert "npm ci" in calls
        assert "npm ls --depth=0" in calls
