"""Contracts for changed-path-gated browser-runtime CI coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.yaml_helper import load_document
from yoke_core.tools.impacted_tests import build_import_index, select


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
BROWSER_RUNTIME_WORKFLOW = WORKFLOWS / "browser-runtime-tests.yml"
YOKE_CI = WORKFLOWS / "yoke-ci.yml"
DEPS_ACTION = REPO_ROOT / ".github" / "actions" / "install-playwright-deps" / "action.yml"


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


def _deps_steps() -> list[dict]:
    return load_document(DEPS_ACTION)["runs"]["steps"]


def test_chromium_os_deps_install_through_the_bounded_action() -> None:
    # On 2026-11-11 an unresolvable Ubuntu mirror hung Playwright's unbounded
    # --with-deps apt install; Platform's PLAT-415 action is the shared shape.
    job = load_document(BROWSER_RUNTIME_WORKFLOW)["jobs"]["browser-runtime"]
    step = _step(job, "Install Chromium OS dependencies")
    assert step["uses"] == "./.github/actions/install-playwright-deps"
    assert step["with"] == {"working-directory": "${{ env.BROWSER_RUNTIME_DIR }}"}
    assert step["timeout-minutes"] <= 10 < job["timeout-minutes"]
    assert "run" not in step
    assert not [s for s in job["steps"] if "--with-deps" in str(s.get("run"))]
    detect = _step(job, "Detect browser-runtime changes")["run"]
    assert ".github/actions/install-playwright-deps/action.yml" in detect


def test_cache_key_covers_image_playwright_version_and_package_set() -> None:
    plan = _deps_steps()[0]["run"]
    assert "npx --no-install playwright install-deps --dry-run chromium" in plan
    assert "${ImageOS}-${ImageVersion}" in plan and "${version}-${digest}" in plan
    restore, save = _deps_steps()[1], _deps_steps()[-1]
    assert restore["uses"].startswith("actions/cache/restore@")
    assert save["uses"].startswith("actions/cache/save@")
    assert "cache-hit != 'true'" in save["if"]


def test_install_runs_with_networking_disabled() -> None:
    install = _deps_steps()[3]["run"]
    assert 'sudo unshare --net -- dpkg -i "$DEBS"/*.deb' in install
    assert "apt-get" not in install


def test_miss_tries_ubuntu_then_one_signed_independent_mirror_bounded() -> None:
    download = _deps_steps()[2]
    assert "cache-hit != 'true'" in download["if"]
    script = download["run"]
    assert script.index("Ubuntu's configured mirror") < script.index("mirrors.edge.kernel.org")
    assert 'timeout --kill-after=10 "$attempt_seconds" apt-get' in script
    # GitHub runs bash -e: each bounded call captures its status so a timeout
    # reaches the named error instead of ending the step with a bare 124.
    assert script.count("|| status=$?") == 2
    assert "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg" in script
    for option in ("Acquire::Retries", "Acquire::http::Timeout", "Acquire::https::Timeout",
                   "APT::Update::Error-Mode=any", "Dir::State::Lists="):
        assert option in script
    for forbidden in ("trusted=yes", "allow-unauthenticated", "AllowInsecureRepositories", "apt-key"):
        assert forbidden not in script
    assert "::error title=install-playwright-deps download::" in script


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
