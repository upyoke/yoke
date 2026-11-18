"""Container bootstrap modules import on Windows and refuse container actions."""

from types import SimpleNamespace

import pytest

from yoke_contracts.self_host_bootstrap import (
    IMPORT_UNIVERSE_ARG,
    RECOVER_IMPORT_CREDENTIAL_ARG,
)
from yoke_core.tools import self_host_import_supervisor as supervisor
from yoke_core.tools import self_host_server_bootstrap as bootstrap

pytestmark = pytest.mark.windows


@pytest.mark.parametrize(("tool", "argv"), [
    (supervisor, [IMPORT_UNIVERSE_ARG]),
    (supervisor, [RECOVER_IMPORT_CREDENTIAL_ARG]),
    (bootstrap, []),
    (bootstrap, ["--healthcheck"]),
    (bootstrap, [IMPORT_UNIVERSE_ARG]),
    (bootstrap, [RECOVER_IMPORT_CREDENTIAL_ARG]),
])
def test_posix_container_entrypoints_refuse_windows_before_actions(tool, argv, monkeypatch, capsys):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Windows refusal performed a container action")

    monkeypatch.setattr(tool, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(supervisor, "signal", SimpleNamespace(SIGUSR1=1, signal=unexpected))
    monkeypatch.setattr(supervisor, "subprocess", SimpleNamespace(Popen=unexpected))
    monkeypatch.setattr(bootstrap, "receive_bootstrap_handoff", unexpected)
    monkeypatch.setattr(bootstrap, "materialize_self_host_runtime_secrets", unexpected)
    monkeypatch.setattr(bootstrap, "_run_healthcheck_as_runtime_user", unexpected)
    assert tool.main(argv) == 1
    refusal = capsys.readouterr().err
    assert f"{tool.__name__.rsplit('.', 1)[-1]}_platform_unsupported" in refusal
    assert "POSIX self-host container" in refusal
    assert "Traceback" not in refusal
