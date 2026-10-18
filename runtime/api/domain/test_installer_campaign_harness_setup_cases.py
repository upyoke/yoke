"""The late-install campaign uses a real Git inventory and isolated writers."""

from pathlib import Path

from yoke_core.domain.installer_campaign_harness_setup_cases import run_probe


def test_late_harness_scripted_probe(monkeypatch, capsys):
    from yoke_contracts.harness_machine_hooks import HarnessMachineHooks

    monkeypatch.setattr(
        HarnessMachineHooks,
        "home_path",
        lambda self, environ=None: Path.home() / self.home.removeprefix("~/"),
    )
    run_probe()
    assert "three Git paths ready in one relay cycle" in capsys.readouterr().out
