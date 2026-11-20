"""Unusable argv paths receive a refusal; internal filesystem defects propagate."""

import errno
from contextlib import nullcontext
from pathlib import Path

import pytest

from yoke_cli import command_router as router
from yoke_cli.config import connection_selection
from yoke_harness import harness_sandbox_recovery


@pytest.fixture
def route(monkeypatch):
    monkeypatch.setattr(connection_selection, "command_connection", lambda *a: nullcontext())
    for name in ("control_plane_locality", "propagated_session_identity", "read_output_scope"):
        monkeypatch.setattr(router, name, lambda *a: nullcontext())
    monkeypatch.setattr(harness_sandbox_recovery, "sandbox_recovery", lambda: None)

    def invoke(argv, adapter):
        monkeypatch.setattr(
            router, "resolve", lambda args: (tuple(args[:2]), None, adapter, args[2:])
        )
        return router.route_command(argv)

    return invoke


@pytest.fixture
def raising_path_checks(monkeypatch):
    """Exercise raised OS errors even on Python versions that return False."""
    def configure(argument):
        for name in ("is_file", "is_dir"):
            original = getattr(Path, name)

            def check(path, *args, _original=original, **kwargs):
                if path.name == argument:
                    raise OSError(errno.ENAMETOOLONG, "File name too long", str(path))
                return _original(path, *args, **kwargs)

            monkeypatch.setattr(Path, name, check)

    return configure


@pytest.mark.parametrize("argument", [" ".join(f"test_{i}.py" for i in range(128)), "x" * 5000], ids=["unsplit-list", "long-name"])
def test_watch_gate_refuses_long_path_arguments(route, capsys, argument, raising_path_checks):
    from yoke_core.tools.gate_admission import is_heavy_invocation

    raising_path_checks(argument)
    argv = ["watch", "pytest", "--print-streaming-pair", "--local", "--", argument]
    assert route(argv, lambda args: is_heavy_invocation(args[3:])) == 2
    error = capsys.readouterr().err
    assert "path_argument_unusable: ENAMETOOLONG" in error
    assert "Traceback" not in error
    assert len(error) < 400
    assert ("unsplit path list" in error) == (" " in argument)
    assert argument[:80] + "…" in error


@pytest.mark.parametrize("code", [errno.EACCES, errno.ELOOP, errno.ENOENT, errno.EINVAL])
@pytest.mark.parametrize("node_id", [False, True])
@pytest.mark.parametrize("absolute", [False, True])
def test_file_argument_os_errors_are_named(route, capsys, code, node_id, absolute):
    path = "unusable.py"
    token = path + ("::TestThing::test_it" if node_id else "")

    def adapter(args):
        raise OSError(code, "cannot use path", str(Path(path).absolute()) if absolute else path)

    assert route(["files", "read", token], adapter) == 2
    error = capsys.readouterr().err
    assert f"path_argument_unusable: {errno.errorcode[code]}" in error
    assert repr(token) in error
    assert "cannot use path" in error
    assert "unsplit path list" not in error


def test_second_filename_is_matched(route, capsys):
    def adapter(args):
        raise OSError(errno.EACCES, "cannot rename", "internal", None, "destination")

    assert route(["files", "move", "destination"], adapter) == 2
    assert "'destination'" in capsys.readouterr().err


@pytest.mark.parametrize("filename", ["internal-config", None, "path.py.extra"])
def test_non_argv_errors_still_propagate(route, filename):
    failure = OSError(errno.EIO, "internal defect", filename)

    def adapter(args):
        raise failure

    with pytest.raises(OSError) as raised:
        route(["files", "read", "path.py::test_one"], adapter)
    assert raised.value is failure


def test_normal_paths_node_ids_and_keyword_expressions_pass_through(route, tmp_path):
    path = tmp_path / "test_file.py"
    path.write_text("def test_one(): pass\n")
    arguments = [str(path), f"{path}::test_one", "-k", "one or two"]
    seen = []

    def adapter(args):
        seen.extend(args)
        assert Path(args[0]).is_file()
        return 0

    assert route(["watch", "pytest", *arguments], adapter) == 0
    assert seen == arguments


@pytest.mark.parametrize("argument", [" ".join(f"test_{i}.py" for i in range(128)), "x" * 4997 + ".py"], ids=["unsplit-list", "long-name"])
def test_watch_command_boundary_refuses_long_arguments(
    route, capsys, argument, monkeypatch, raising_path_checks
):
    from yoke_core.tools import watch_pytest

    raising_path_checks(argument)
    # Test the real watcher path checks without provisioning a project Python.
    monkeypatch.setattr(watch_pytest, "project_parallel_args", lambda args, **kw: args)
    monkeypatch.setattr(
        watch_pytest._source_pythonpath, "verified_source_environment",
        lambda root, env: (env, None),
    )
    assert router.route_command([
        "watch", "pytest", "--print-streaming-pair", "--local", "--", argument,
    ]) == 2
    error = capsys.readouterr().err
    assert "path_argument_unusable: ENAMETOOLONG" in error
    assert "Traceback" not in error
