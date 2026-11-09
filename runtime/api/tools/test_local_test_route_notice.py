"""Local routing reasons reach foreground callers and printed watch recipes."""

import pytest

from yoke_core.domain import watch_capture_binding as _watch_capture_binding
from yoke_core.tools import pytest_remote_selection as routing
from yoke_core.tools import run_tests, watch_pytest

pytestmark = pytest.mark.usefixtures("bound_project_context")


def _missing_workflow(monkeypatch, root):
    from yoke_core.domain import project_ci_workflow, yoke_connected_env

    monkeypatch.delenv(routing.LOCAL_ENV, raising=False)
    monkeypatch.delenv("YOKE_QA_CANDIDATE_TREE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(routing, "required_local_project", lambda *a, **k: "sample")
    monkeypatch.setattr(yoke_connected_env, "load_active", lambda: object())
    monkeypatch.setattr(
        project_ci_workflow,
        "project_ci_workflow_settings",
        lambda _: {"workflow_file": "verify.yml"},
    )
    monkeypatch.chdir(root)
    (root / "tests").mkdir()
    (root / "tests/test_example.py").write_text("def test_example(): pass\n")


def _front_door(monkeypatch, module):
    monkeypatch.setattr(
        module.verification_tree_binding,
        "evaluate_run",
        lambda **_: module.verification_tree_binding.TreeBindingVerdict(),
    )
    monkeypatch.setattr(
        module._source_pythonpath,
        "verified_source_environment",
        lambda root, env: (dict(env), None),
    )


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("print_step", [False, True])
def test_watch_reports_local_reason(monkeypatch, tmp_path, capsys, local, print_step):
    _missing_workflow(monkeypatch, tmp_path)
    _front_door(monkeypatch, watch_pytest)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    monkeypatch.setattr(watch_pytest, "project_parallel_args", lambda args, **_: args)
    # Stop the foreground run at the normal argument boundary, after routing.
    # The print step continues through recipe rendering without launching pytest.
    if not print_step:
        monkeypatch.setattr(
            watch_pytest._watch_pytest_args,
            "argument_shape_refusal",
            lambda *a: ("test boundary", 2),
        )
    args = (["--local"] if local else []) + (
        ["--print-streaming-pair"] if print_step else []
    )
    assert watch_pytest.main([*args, "--", "tests/test_example.py"]) == (
        0 if print_step else 2
    )
    output = capsys.readouterr()
    reason = (
        "--local was passed"
        if local
        else "this tree has no .github/workflows/yoke-tests-selection.yml"
    )
    assert f"# watch_pytest local-run: {reason}\n" in output.err
    if print_step:
        assert "yoke watch pytest" in output.out
    else:
        progress = next(tmp_path.rglob("*progress*"))
        assert reason in progress.read_text()


@pytest.mark.parametrize("local", [False, True])
def test_runner_reports_local_reason(monkeypatch, tmp_path, capsys, local):
    _missing_workflow(monkeypatch, tmp_path)
    _front_door(monkeypatch, run_tests)
    monkeypatch.setattr(run_tests, "_is_yoke_backend_verification", lambda *a: True)
    monkeypatch.setattr(run_tests, "_prepare_yoke_backend_env", lambda *a: False)
    assert (
        run_tests.run(["tests/test_example.py"], repo_root=tmp_path, local=local) == 1
    )
    reason = (
        "--local was passed"
        if local
        else "this tree has no .github/workflows/yoke-tests-selection.yml"
    )
    assert capsys.readouterr().err == f"running on this machine: {reason}\n"


@pytest.mark.parametrize("wrapper", ["watch", "runner"])
def test_remote_route_adds_no_local_notice(monkeypatch, tmp_path, capsys, wrapper):
    route = routing.RemoteRoute(
        tmp_path, "sample", "select.yml", "org/repo", "work", "a" * 40, "b" * 40, ()
    )
    monkeypatch.setattr(routing, "resolve_route", lambda *a, **k: route)
    module = watch_pytest if wrapper == "watch" else run_tests
    _front_door(monkeypatch, module)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_example.py").write_text("def test_example(): pass\n")
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    if wrapper == "watch":
        monkeypatch.setattr(watch_pytest.watch_pytest_remote, "run", lambda *a, **k: 0)
        assert watch_pytest.main(["--", "tests/test_example.py"]) == 0
    else:
        monkeypatch.setattr(run_tests, "_run_remote", lambda _: 0)
        assert run_tests.run(["tests/test_example.py"], repo_root=tmp_path) == 0
    assert capsys.readouterr().err == ""


def test_capture_notes_are_visible_and_retained(tmp_path, capsys):
    progress = tmp_path / "progress.log"
    _watch_capture_binding.note_claimed_capture(progress, "selection starting")
    assert capsys.readouterr().err == "selection starting\n"
    assert progress.read_text() == "selection starting\n"
