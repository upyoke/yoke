"""The source smoke resolves its project through the checkout registration."""

import json
from types import SimpleNamespace

from runtime.api.tools.product_runner_commands import Commands
from runtime.api.tools.product_runner_source_tests import run_source_tests


def test_source_tests_register_their_own_project_before_pytest(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    seen = []
    project_id = 42

    def run(argv, **kwargs):
        assert kwargs["cwd"] == root
        assert "YOKE_PROJECT" not in kwargs["env"]
        seen.append(argv)
        if argv[1:3] == ["projects", "create"]:
            assert argv == [
                "yoke", "projects", "create", "--slug", "yoke-source",
                "--name", "Yoke source", "--public-item-prefix", "SRC",
                "--default-branch", "main", "--github-sync-mode", "disabled", "--json",
            ]
            payload = {"success": True, "result": {"project": {"id": project_id}}}
        else:
            payload = {}
        if "pytest" in argv:
            assert seen[0][1:3] == ["projects", "create"]
            assert seen[1] == [
                "yoke", "project", "register", str(root),
                "--project-id", str(project_id), "--json",
            ]
            assert "--project" not in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("runtime.api.tools.product_runner_commands.subprocess.run", run)
    run_source_tests(root, Commands(tmp_path, {}))
    assert sum("pytest" in argv for argv in seen) == 1
