"""Every harness registers with the selected connection's machine checkout."""

import pytest
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_cli.config import writer as machine_config_writer
from runtime.harness.hook_project_scope_test_support import project_map as project_map
from yoke_core.hooks import session_lifecycle_client


@pytest.mark.windows_only(reason="native drive resolution")
def test_local_registration_lookup_resolves_slash_prefixed_workspace(tmp_path, project_map):
    project_map["connection_projects"]["local"] = [
        {"checkout": str(tmp_path), "project_id": 7}
    ]
    reported = "/" + tmp_path.drive.lower() + tmp_path.as_posix()[2:]
    assert session_lifecycle_client._project_id_for_root(reported) == 7


@pytest.mark.parametrize(
    "executor,provider",
    [("claude-code", "anthropic"), ("codex", "openai"), ("cursor", "cursor")],
)
@pytest.mark.parametrize("selected", ["local", "prod", "prod-db-admin", "stage"])
def test_registration_uses_selected_connection_mapping(
    tmp_path, monkeypatch, executor, provider, selected
):
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    token = tmp_path / "token"
    token.write_text("test")
    machine_config_writer.set_connection(
        selected,
        transport="https",
        api_url=f"https://{selected}.example.test",
        token_file=str(token),
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    machine_config_writer.register_project(checkout, 4)
    monkeypatch.setenv("YOKE_ENV", selected)
    monkeypatch.setattr(
        session_lifecycle_client, "_relay_owns_registration", lambda: False
    )
    monkeypatch.setattr(
        session_lifecycle_client, "_local_authority_active", lambda: True
    )
    seen = []
    monkeypatch.setattr(
        "yoke_core.hooks.registration_in_process._register_in_process",
        lambda *args, project_id=None, **kwargs: seen.append(project_id) or "registered",
    )
    assert (
        session_lifecycle_client.register_harness_session(
            root=str(checkout),
            session_id="test-session",
            executor=executor,
            provider=provider,
            model_facts=SessionModelFacts(requested_model="test-model"),
            native_thread_id="",
        )
        == "registered"
    )
    assert seen == [4]
