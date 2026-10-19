"""Wheel smoke for the field-note help surface without the engine package.

The shared interpreter runs with site loading disabled and a filtered view of
installed packages. No engine or source-checkout package enters that view.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def smoke(
    tmp_path: Path,
    product_wheelhouse: Path,
    product_venv: Path,
) -> None:
    venv_dir = product_venv
    venv_python = venv_dir / "bin" / "python"
    site_result = _run(
        [
            str(venv_python),
            "-I",
            "-c",
            "import sysconfig; print(sysconfig.get_path('purelib'))",
        ],
        cwd=tmp_path,
    )
    installed_site = Path(site_result.stdout.strip())
    client_site = tmp_path / "client-site"
    client_site.mkdir()
    for entry in installed_site.iterdir():
        if not entry.name.startswith("yoke_core"):
            (client_site / entry.name).symlink_to(
                entry, target_is_directory=entry.is_dir()
            )
    yoke = tmp_path / "yoke"
    yoke.write_text(
        f"#!{venv_python} -S\nfrom yoke_cli.main import main\nraise SystemExit(main())\n",
        encoding="utf-8",
    )
    yoke.chmod(0o755)

    external_project = tmp_path / "external-project"
    external_project.mkdir()
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{venv_dir / 'bin'}:{BASE_PATH}",
        "PYTHONPATH": str(client_site),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }

    import_check = _run(
        [
            str(venv_python),
            "-S",
            "-c",
            "import importlib.util; "
            "assert importlib.util.find_spec('yoke_core') is None; "
            "assert importlib.util.find_spec('runtime') is None",
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
    assert (
        "File a field note each time a recipe, help text or refusal is wrong"
        in help_result.stdout
    )
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
        [str(venv_python), "-S", "-c", read_script],
        cwd=external_project,
        env=env,
    )
    marker = next(
        line
        for line in read_result.stdout.splitlines()
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
