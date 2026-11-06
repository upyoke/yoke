"""Only the successful validation provisioner publishes a source-run output."""

import pytest

from yoke_core.domain import migration_validation_binding as binding
from yoke_core.tools import source_dev_run, source_validation_binding as subject

COMMAND = ["python3", "-m", subject.PROVISION_MODULE]


@pytest.fixture(autouse=True)
def no_exported_binding(monkeypatch):
    monkeypatch.delenv(binding.YOKE_VALIDATION_DSN_ENV, raising=False)


def _child_binding(tmp_path):
    home = tmp_path / "child"
    path = home / "secrets" / binding.binding_file(binding.YOKE_VALIDATION_DSN_ENV).name
    path.parent.mkdir(parents=True)
    path.write_text("host=local dbname=validation password=private-value")
    return path, {"YOKE_MACHINE_HOME": str(home)}


@pytest.mark.parametrize(
    "command",
    [
        ["python3", "-m", subject.PROVISION_MODULE, "--help"],
        ["python3", "-m", "pytest"],
        ["env", "python3", "-m", subject.PROVISION_MODULE],
        ["python3", "-c", "pass"],
    ],
)
def test_other_commands_never_publish_bindings(tmp_path, command):
    _path, env = _child_binding(tmp_path)
    target = binding.binding_file(binding.YOKE_VALIDATION_DSN_ENV)
    assert subject.persist(command, env) == 0
    assert not target.exists()


def test_persistence_refusal_preserves_old_binding_without_showing_credentials(
    tmp_path, monkeypatch, capsys
):
    binding.write_binding(binding.YOKE_VALIDATION_DSN_ENV, "old-binding")
    _path, env = _child_binding(tmp_path)

    def refuse(*_args):
        raise OSError("private-value")

    monkeypatch.setattr(binding, "write_binding", refuse)
    assert subject.persist(COMMAND, env) == 1
    assert binding.read_binding(binding.YOKE_VALIDATION_DSN_ENV) == "old-binding"
    error = capsys.readouterr().err
    assert "validation_binding_persist_failed" in error
    assert "rerun the provisioning command" in error
    assert "private-value" not in error


@pytest.mark.parametrize("content", [None, "", b"\xff"])
def test_missing_or_unusable_binding_refuses(tmp_path, capsys, content):
    path, env = _child_binding(tmp_path)
    if content is None:
        path.unlink()
    elif isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    assert subject.persist(COMMAND, env) == 1
    assert "validation_binding_persist_failed" in capsys.readouterr().err


def test_failed_source_child_does_not_publish_any_output(monkeypatch, tmp_path):
    monkeypatch.setattr(
        source_dev_run.source_dev_candidate_binding,
        "resolve",
        lambda _lane: (None, None),
    )
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (tmp_path, None, None))
    monkeypatch.setattr(source_dev_run, "_run_bound", lambda *_args: 7)
    monkeypatch.setattr(
        subject, "persist", lambda *_args: pytest.fail("published failed child")
    )
    assert source_dev_run.run(COMMAND) == 7
