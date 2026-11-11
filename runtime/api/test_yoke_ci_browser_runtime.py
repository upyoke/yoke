"""Contracts for changed-path-gated browser-runtime CI coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_core.domain.yaml_helper import load_document
from yoke_core.tools.impacted_tests import build_import_index, select


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
BROWSER_RUNTIME_WORKFLOW = WORKFLOWS / "browser-runtime-tests.yml"
YOKE_CI = WORKFLOWS / "yoke-ci.yml"


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def test_yoke_ci_calls_browser_runtime_gate_after_repo_contracts() -> None:
    workflow = load_document(YOKE_CI)
    job = workflow["jobs"]["browser_runtime"]

    assert job["uses"] == "./.github/workflows/browser-runtime-tests.yml"
    assert job["needs"] == ["repo_contracts", "reuse_coverage"]
    assert " ".join(str(job["if"]).split()) == (
        "${{ !cancelled() && needs.repo_contracts.result == 'success' "
        "&& needs.reuse_coverage.result == 'success' }}"
    )


def test_browser_runtime_workflow_gates_every_expensive_step_on_its_tree() -> None:
    text = BROWSER_RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    assert "\non:\n  workflow_call:\n" in text
    workflow = load_document(BROWSER_RUNTIME_WORKFLOW)

    assert workflow["name"] == "browser-runtime-tests"
    runtime_dir = workflow["env"]["BROWSER_RUNTIME_DIR"]
    assert runtime_dir.endswith("/browser_runtime")
    job = workflow["jobs"]["browser-runtime"]
    detect = _step(job, "Detect browser-runtime changes")["run"]
    assert 'git merge-base HEAD "$base_ref"' in detect
    assert 'git diff --quiet "$base_sha" HEAD -- "$BROWSER_RUNTIME_DIR"' in detect
    assert "should_run=false" in detect
    assert "should_run=true" in detect

    guarded = {
        step["name"]
        for step in job["steps"]
        if "steps.change_scope.outputs.should_run == 'true'" in str(step.get("if"))
    }
    assert guarded == {
        "Set up Node.js",
        "Install browser-runtime dependencies",
        "Install Chromium",
        "Install Chromium OS dependencies",
        "Provision Chromium sandbox",
        "Run browser-runtime tests",
        "Set up Python for Browser case integration",
        "Install Browser case integration dependencies",
        "Run registered Browser case integration",
    }


def test_browser_runtime_workflow_provisions_and_runs_the_locked_suite() -> None:
    job = load_document(BROWSER_RUNTIME_WORKFLOW)["jobs"]["browser-runtime"]

    checkout = _step(job, "Checkout")
    assert checkout["with"]["fetch-depth"] == 0
    assert _step(job, "Install browser-runtime dependencies")["run"] == "npm ci"
    assert _step(job, "Install Chromium")["run"] == (
        "npx --no-install playwright install chromium"
    )
    assert _step(job, "Run browser-runtime tests")["run"] == "npm test"
    provision = _step(job, "Provision Chromium sandbox")
    # browser_apparmor imports the shared detached-process helper (contracts)
    # and the wizard terminal marker (cli).
    assert provision["env"]["PYTHONPATH"] == (
        "packages/yoke-harness/src:packages/yoke-cli/src:packages/yoke-contracts/src"
    )
    assert "ensure_chromium_apparmor(" in provision["run"]
    names = [step["name"] for step in job["steps"]]
    assert names.index("Install Chromium") < names.index(
        "Install Chromium OS dependencies"
    )
    assert names.index("Install Chromium OS dependencies") < names.index(
        "Provision Chromium sandbox"
    )
    assert names.index("Provision Chromium sandbox") < names.index(
        "Run browser-runtime tests"
    )


_STUBS = {
    # Playwright reports missing packages until the stubbed install lands.
    "npx": """#!/bin/bash
if [ -e "$STATE/installed" ]; then echo "All system dependencies are installed."; exit 0; fi
printf 'Missing system dependencies (2):\\n  libgbm1\\n  libnss3\\n'; exit 1
""",
    # A hung mirror is the bound expiring: GNU timeout exits 124.
    "timeout": """#!/bin/bash
echo "timeout $*" >> "$STATE/calls"
[ -e "$STATE/hang" ] && exit 124
shift 2; exec "$@"
""",
    "sudo": '#!/bin/bash\nexec "$@"\n',
    "apt-get": """#!/bin/bash
echo "apt-get $*" >> "$STATE/calls"
case " $* " in *" install "*) touch "$STATE/installed" ;; esac
""",
}


def _run_os_deps_step(tmp_path: Path, *state: str) -> tuple[subprocess.CompletedProcess, str]:
    job = load_document(BROWSER_RUNTIME_WORKFLOW)["jobs"]["browser-runtime"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in _STUBS.items():
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    for name in state:
        (tmp_path / name).touch()
    result = subprocess.run(
        ["bash", "-c", _step(job, "Install Chromium OS dependencies")["run"]],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "STATE": str(tmp_path)},
        capture_output=True, text=True, timeout=30, check=False,
    )
    calls = tmp_path / "calls"
    return result, calls.read_text() if calls.exists() else ""


def test_os_deps_step_is_bounded() -> None:
    job = load_document(BROWSER_RUNTIME_WORKFLOW)["jobs"]["browser-runtime"]
    step = _step(job, "Install Chromium OS dependencies")
    assert step["timeout-minutes"] == 5
    assert not [s for s in job["steps"] if "--with-deps" in str(s.get("run"))]


def test_os_deps_step_skips_apt_when_the_image_has_every_package(tmp_path: Path) -> None:
    result, calls = _run_os_deps_step(tmp_path, "installed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "skipping apt" in result.stdout
    assert calls == ""


def test_os_deps_step_installs_missing_packages_with_bounded_apt(tmp_path: Path) -> None:
    result, calls = _run_os_deps_step(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.splitlines() == [
        "timeout --kill-after=10 90 sudo apt-get -o Acquire::Retries=3 update",
        "apt-get -o Acquire::Retries=3 update",
        "timeout --kill-after=10 150 sudo apt-get -o Acquire::Retries=3 install"
        " --yes --no-install-recommends libgbm1 libnss3",
        "apt-get -o Acquire::Retries=3 install --yes --no-install-recommends"
        " libgbm1 libnss3",
    ]


def test_os_deps_step_fails_named_when_the_mirror_hangs(tmp_path: Path) -> None:
    result, calls = _run_os_deps_step(tmp_path, "hang")
    assert result.returncode == 1
    assert result.stdout.strip().endswith(
        "::error title=browser_runtime_os_deps_failed::browser_runtime_os_deps_failed:"
        " apt-get update failed or exceeded 90s (exit 124). Recovery: check the"
        " runner's Ubuntu apt mirror connectivity, then rerun this job."
    )
    assert calls.splitlines() == [
        "timeout --kill-after=10 90 sudo apt-get -o Acquire::Retries=3 update",
    ]


@pytest.mark.parametrize("workflow", [BROWSER_RUNTIME_WORKFLOW, YOKE_CI])
def test_workflow_reader_survives_bounded_selection(
    tmp_path: Path, workflow: Path
) -> None:
    changed = str(workflow.relative_to(REPO_ROOT))
    subject = tmp_path / changed
    subject.parent.mkdir(parents=True)
    subject.write_text("name: example\n")
    consumer = "runtime/api/test_yoke_ci_browser_runtime.py"
    test = tmp_path / consumer
    test.parent.mkdir(parents=True)
    test.write_text("def test_contract(): pass\n")

    selection = select([changed], build_import_index(tmp_path), bounded=True)

    assert consumer in selection.files
    assert f"browser_runtime_workflow_contract:{changed}" in selection.widening_triggers
