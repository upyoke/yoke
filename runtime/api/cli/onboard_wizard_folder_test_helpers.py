"""Offline folder validation and checkout identity for wizard flow tests."""

from pathlib import Path


def stub_folder_environment(monkeypatch) -> None:
    """Accept any folder path so flow scenarios can type fictional paths.

    The create/clone folder steps validate the real filesystem (a path must be
    empty/new with a writable parent). Flow scenarios that exercise downstream
    routing type host-independent fictional paths (``/home/code/widget``), so the
    filesystem validators are no-oped here. The validators' real behavior is
    covered directly by the validator unit suite, not these flow scenarios.
    """
    from yoke_cli.config import onboard_input_validation as validation
    from yoke_contracts.machine_config import schema_projects

    # Checkout/worktree identity has its own contract tests. Keep real machine
    # mappings and manifests here, without probing Git for fictional folders.
    monkeypatch.setattr(
        schema_projects, "main_checkout", lambda root: Path(root).expanduser().resolve()
    )

    monkeypatch.setattr(validation, "validate_create_target_folder", lambda _p: None)
    monkeypatch.setattr(validation, "validate_clone_target_folder", lambda _p: None)

