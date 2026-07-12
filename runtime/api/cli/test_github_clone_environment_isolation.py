"""Clone environment rebuilding and user-facing fallback provenance."""

from __future__ import annotations

import json

from yoke_cli.config import project_clone_support as clone
from yoke_cli.config import project_git_transport as transport


def test_hostile_ephemeral_git_config_and_askpass_are_rebuilt() -> None:
    hostile = {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": "!credential-sentinel",
        "GIT_CONFIG_KEY_1": "http.extraHeader",
        "GIT_CONFIG_VALUE_1": "AUTHORIZATION: hostile-secret",
        "GIT_CONFIG_PARAMETERS": "'http.extraHeader=hostile-secret'",
        "GIT_ASKPASS": "/tmp/credential-sentinel",
        "SSH_ASKPASS": "/tmp/ssh-sentinel",
        "GIT_SSH_COMMAND": "ssh -o ProxyCommand=hostile",
        "HTTPS_PROXY": "https://proxy.example",
        "GIT_SSL_CAINFO": "/trusted/ca.pem",
    }

    env = transport.git_config_env(("safe.key=value",), base=hostile)

    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "safe.key"
    assert env["GIT_CONFIG_VALUE_0"] == "value"
    assert "GIT_CONFIG_KEY_1" not in env
    assert "GIT_CONFIG_PARAMETERS" not in env
    assert "hostile-secret" not in json.dumps(env)
    assert env["GIT_ASKPASS"] == ""
    assert env["SSH_ASKPASS"] == ""
    assert env["SSH_ASKPASS_REQUIRE"] == "never"
    assert "ProxyCommand=hostile" not in env["GIT_SSH_COMMAND"]
    assert env["HTTPS_PROXY"] == "https://proxy.example"
    assert env["GIT_SSL_CAINFO"] == "/trusted/ca.pem"


def test_clone_progress_copy_names_anonymous_fallback() -> None:
    text = " ".join(
        clone.clone_progress_lines(
            "acme/widgets",
            clone.CloneOutcome(
                used_token=True,
                origin_url="https://github.com/acme/widgets.git",
            ),
        )
    )
    assert "Anonymous access couldn't reach it" in text
    assert "Your git setup couldn't reach it" not in text
