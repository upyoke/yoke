"""Guards for GitHub Actions self-hosted runner routing knobs."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.yaml_helper import parse_document

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def test_product_smoke_runs_the_diagnostic_on_four_runners():
    body = (WORKFLOWS / "product-smoke.yml").read_text(encoding="utf-8")
    matrix = parse_document(body)["jobs"]["smoke"]["strategy"]["matrix"]["include"]
    assert {
        (entry["runner"], entry["os"], entry["architecture"]) for entry in matrix
    } == {
        ("ubuntu-24.04", "Ubuntu 24.04", "x86_64"),
        ("ubuntu-24.04-arm", "Ubuntu 24.04", "arm64"),
        ("macos-latest", "macOS 26", "arm64"),
        ("windows-2025", "Windows 2025Server", "x86_64"),
    }
    smoke_steps = {
        step["if"]: step["run"]
        for step in parse_document(body)["jobs"]["smoke"]["steps"]
        if "product_runner_smoke.py" in step.get("run", "")
        or "product_runner_linux_account.py" in step.get("run", "")
    }
    # Every leg runs the whole stage list: Linux through its disposable
    # account, macOS and Windows directly; no leg stops at an early stage.
    assert set(smoke_steps) == {"runner.os != 'Linux'", "runner.os == 'Linux'"}
    assert not any("--through" in command for command in smoke_steps.values())


def test_multi_os_suite_uses_a_windows_and_macos_matrix():
    body = (WORKFLOWS / "yoke-suite.yml").read_text(encoding="utf-8")
    strategy = parse_document(body)["jobs"]["suite"]["strategy"]
    assert strategy["matrix"]["os"] == ["windows", "macos"]
    assert {(entry["os"], entry["runner"]) for entry in strategy["matrix"]["include"]} == {
        ("windows", "windows-2025"),
        ("macos", "macos-latest"),
    }


@pytest.mark.posix_only(reason="Exercises the Linux plan step's Bash source")
@pytest.mark.parametrize("uppercase", [False, True])
def test_multi_os_suite_resolves_sha_before_plan_and_matrix_checkout(tmp_path, uppercase):
    import json
    import os
    import subprocess

    body = (WORKFLOWS / "yoke-suite.yml").read_text(encoding="utf-8")
    jobs = parse_document(body)["jobs"]
    plan = jobs["plan"]
    assert plan["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    assert plan["steps"][0]["with"]["fetch-depth"] == 0
    assert plan["outputs"]["commit"] == "${{ steps.resolve_commit.outputs.commit }}"
    assert jobs["suite"]["steps"][0]["with"]["ref"] == "${{ needs.plan.outputs.commit }}"
    resolver = next(step["run"] for step in plan["steps"] if step.get("id") == "resolve_commit")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    for subject in ("suite target", "dispatch ref"):
        git("-c", "user.name=Tester", "-c", "user.email=test@example.com",
            "commit", "--allow-empty", "-qm", subject)
    commit = git("rev-parse", "HEAD^")

    output = tmp_path / "output"
    summary = tmp_path / "summary"
    prefix = commit[:10]
    env = {
        **os.environ, "SUITE_REVISION": prefix.upper() if uppercase else prefix,
        "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary),
        "RUNNER_TEMP": str(tmp_path),
    }
    # Use the system Bash, which is 3.2 on macOS.
    subprocess.run(["/bin/bash", "-e", "-c", resolver], cwd=tmp_path, env=env, check=True)
    assert output.read_text() == f"commit={commit}\n"
    assert git("rev-parse", "HEAD") == commit
    assert commit in summary.read_text()
    assert json.loads((tmp_path / "suite-commit.json").read_text()) == {"tested_sha": commit}

    invalid = subprocess.run(
        ["/bin/bash", "-e", "-c", resolver], cwd=tmp_path,
        env={**env, "SUITE_REVISION": "unknown-sha"}, capture_output=True, text=True,
    )
    assert invalid.returncode == 1
    assert "unknown-sha" in invalid.stderr
    assert "full commit SHA" in invalid.stderr
