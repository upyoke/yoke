"""Wheel smoke for the field-note help surface without the engine package.

External projects use the packaged client boundary.  This test installs only
``yoke-cli`` and ``yoke-contracts`` into a disposable environment, blocks every
source-checkout path, and proves field-note argument parsing remains available
without ``yoke_core``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from runtime.api.product_boundary_isolation import write_sitecustomize
from yoke_core.tools.build_release import create_seeded_pip_venv


BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_field_note_help_runs_from_core_less_product_wheels(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    venv_dir = tmp_path / "venv"
    create_seeded_pip_venv(venv_dir, system_site_packages=True)
    venv_python = venv_dir / "bin" / "python"
    yoke = venv_dir / "bin" / "yoke"
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--ignore-installed",
            "--no-deps",
            "--no-index",
            "--find-links",
            str(product_wheelhouse),
            "yoke-cli",
            "yoke-contracts",
        ],
        cwd=tmp_path,
        timeout=180,
    )

    external_project = tmp_path / "external-project"
    external_project.mkdir()
    sitecustomize_dir = write_sitecustomize(
        tmp_path,
        repo_root=REPO_ROOT,
        allowed_repo_paths=(),
    )
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{venv_dir / 'bin'}:{BASE_PATH}",
        "PYTHONPATH": str(sitecustomize_dir),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }

    import_check = _run(
        [
            str(venv_python),
            "-c",
            "import importlib.util; "
            "assert importlib.util.find_spec('yoke_core') is None",
        ],
        cwd=external_project,
        env=env,
    )
    assert import_check.stdout == ""

    help_result = _run(
        [str(yoke), "ouroboros", "field-note", "append", "--help"],
        cwd=external_project,
        env=env,
    )
    assert "Append a structured field-note" in help_result.stdout
    assert "failed,new,unclear,observation" in help_result.stdout
    assert "≤4000 chars" in help_result.stdout

    invalid_kind = _run(
        [
            str(yoke),
            "ouroboros",
            "field-note",
            "append",
            "--kind",
            "unsupported",
            "--evidence",
            "boundary check",
        ],
        cwd=external_project,
        env=env,
        check=False,
    )
    assert invalid_kind.returncode == 2
    assert "invalid choice" in invalid_kind.stderr
    assert "yoke_core" not in invalid_kind.stderr

    read_script = r"""
import json

from yoke_cli.commands import _helpers
from yoke_cli.main import main
from yoke_contracts.api.function_call import FunctionCallResponse

requests = []


def fake_call_dispatcher(**kwargs):
    requests.append({
        "function": kwargs["function_id"],
        "target": kwargs["target"].model_dump(mode="json"),
        "payload": kwargs["payload"],
    })
    result = (
        {"entries": [{"id": 73, "category": "field-note-observation"}]}
        if kwargs["function_id"].endswith(".list")
        else {"entry": {"id": 73, "category": "field-note-observation"}}
    )
    return FunctionCallResponse(
        success=True,
        function=kwargs["function_id"],
        version="v1",
        result=result,
    )


_helpers.ensure_handlers_loaded = lambda: None
_helpers.call_dispatcher = fake_call_dispatcher
assert main([
    "ouroboros", "field-note", "list", "--limit", "1", "--json",
]) == 0
assert main([
    "ouroboros", "field-note", "get", "73", "--json",
]) == 0
print("__FIELD_NOTE_REQUESTS__" + json.dumps(requests, sort_keys=True))
"""
    read_result = _run(
        [str(venv_python), "-c", read_script],
        cwd=external_project,
        env=env,
    )
    marker = next(
        line for line in read_result.stdout.splitlines()
        if line.startswith("__FIELD_NOTE_REQUESTS__")
    )
    requests = json.loads(marker.removeprefix("__FIELD_NOTE_REQUESTS__"))
    assert [request["function"] for request in requests] == [
        "ouroboros.field_note.list",
        "ouroboros.field_note.get",
    ]
    assert [request["target"]["kind"] for request in requests] == [
        "global",
        "global",
    ]
    assert all(request["target"].get("project_id") is None for request in requests)


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
    if env is None:
        run_env.pop("PYTHONPATH", None)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check:
        assert result.returncode == 0, (
            f"command failed with {result.returncode}: {result.args!r}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result
