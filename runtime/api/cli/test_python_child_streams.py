"""Windows Python child entry points carry UTF-8 through captured streams."""

from __future__ import annotations

import ast
import io
import subprocess
import sys
from pathlib import Path

from yoke_cli.commands import merge_item_local_runtime
from yoke_contracts import standard_streams


def test_merge_item_child_prints_unicode_to_legacy_pipes(monkeypatch):
    output, errors = io.BytesIO(), io.BytesIO()
    with (
        io.TextIOWrapper(output, encoding="cp1252", write_through=True) as stdout,
        io.TextIOWrapper(errors, encoding="cp1252", write_through=True) as stderr,
        monkeypatch.context() as patch,
    ):
        patch.setattr(sys, "stdout", stdout)
        patch.setattr(sys, "stderr", stderr)

        def run(argv):
            assert argv == ["ITEM-1"]
            print("Merging branch: ITEM-1 → main")
            print("ITEM-1 → main", file=sys.stderr)
            return 0

        patch.setattr(merge_item_local_runtime, "run", run)
        assert merge_item_local_runtime.main(["ITEM-1"]) == 0
        assert output.getvalue().decode("utf-8").splitlines() == [
            "Merging branch: ITEM-1 → main"
        ]
        assert errors.getvalue().decode("utf-8").splitlines() == ["ITEM-1 → main"]


def test_python_module_launches_use_the_windows_utf8_environment(monkeypatch):
    commands = Path(merge_item_local_runtime.__file__).parent
    launches = []
    for path in sorted(commands.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            argv = node.args[0]
            if not isinstance(argv, (ast.List, ast.Tuple)) or len(argv.elts) < 3:
                continue
            if [ast.unparse(arg) for arg in argv.elts[:2]] != ["sys.executable", "'-m'"]:
                continue
            launch = f"{path.relative_to(commands)}:{node.lineno} ({ast.unparse(argv.elts[2])})"
            launches.append(launch)
            env = next((kw.value for kw in node.keywords if kw.arg == "env"), None)
            assert isinstance(env, ast.Call), launch
            assert ast.unparse(env.func) == "utf8_python_child_env", launch

    assert launches, "no CLI Python module launches were checked"
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    with monkeypatch.context() as patch:
        patch.setattr(standard_streams.sys, "platform", "win32")
        env = standard_streams.utf8_python_child_env()

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; print(sys.stdout.encoding); print(sys.stderr.encoding); "
            "print(chr(0x2192)); print(chr(0x2192), file=sys.stderr)",
        ],
        env=env,
        check=True,
        capture_output=True,
    )
    assert child.stdout.decode("utf-8").splitlines() == ["utf-8", "utf-8", "→"]
    assert child.stderr.decode("utf-8").splitlines() == ["→"]
