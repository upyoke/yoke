"""Offline checkout identity for flows that type fictional folder paths."""

from yoke_cli.config import existing_project_lookup, onboard_local_checkout_identity


def stub_local_checkout_identity(monkeypatch) -> None:
    """Treat a fictional folder as an unregistered checkout without an origin."""
    monkeypatch.setattr(
        onboard_local_checkout_identity, "inspect", lambda *_: (None, None)
    )
    monkeypatch.setattr(
        existing_project_lookup, "find_local_project_reference", lambda *a, **k: None
    )
