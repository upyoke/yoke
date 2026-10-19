"""A real candidate watcher needs no connection in its isolated machine home."""

import json
import os
import subprocess
from pathlib import Path

from yoke_core.domain.qa_case_candidate_source import candidate_source
from yoke_core.domain.qa_environment_declaration import TestEnvironmentDeclaration


def test_candidate_watcher_runs_tests_with_empty_home(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    reads = []

    def declaration(**_kwargs):
        reads.append(True)
        return TestEnvironmentDeclaration(project="fixture", uv_project=".")

    monkeypatch.setattr(
        "yoke_core.domain.source_python_environment.load_declaration", declaration
    )
    probe = tmp_path / "test_isolated.py"
    probe.write_text(
        "import os\nfrom pathlib import Path\n"
        "def test_home_has_no_connection():\n"
        "    for key in ('HOME', 'YOKE_MACHINE_HOME'):\n"
        "        assert not (Path(os.environ[key]) / 'config.json').exists()\n"
    )
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    home = tmp_path / "home"
    home.mkdir()
    incoming = dict(
        os.environ,
        YOKE_QA_CANDIDATE_TREE=json.dumps({"root": str(root), "head_sha": "a" * 40}),
    )
    with candidate_source(root, incoming) as binding:
        assert binding and not binding.refusal
        child = dict(
            binding.env,
            HOME=str(home),
            YOKE_MACHINE_HOME=str(home),
            YOKE_SCRATCH_ROOT=str(tmp_path / "captures"),
        )
        completed = subprocess.run(
            [
                "yoke",
                "watch",
                "pytest",
                "--local",
                "--",
                "-n",
                "0",
                "-c",
                str(config),
                "--confcutdir",
                str(tmp_path),
                str(probe),
            ],
            cwd=root,
            env=child,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "1 passed" in completed.stdout
        unbound = dict(child)
        unbound.pop("YOKE_QA_CANDIDATE_TREE")
        refused = subprocess.run(
            completed.args,
            cwd=root,
            env=unbound,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert refused.returncode == 3, refused.stdout + refused.stderr
        assert "SOURCE-ENVIRONMENT-DECLARATION" in refused.stdout + refused.stderr
        from yoke_core.domain.source_python_environment import resolve

        inherited = resolve(root, child)
        assert (
            inherited.evidence["declaration"]
            == binding.evidence["environment"]["declaration"]
        )
        binding.inspect("after")
        assert not binding.refusal
        assert reads == [True]
