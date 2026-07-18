"""Machine-config contract tests for HTTPS transport entries."""

from __future__ import annotations

from yoke_contracts.machine_config.schema import validate_payload


def _https_config(tmp_path, token="tok-123", api_url="https://api.example"):
    token_file = tmp_path / "token"
    token_file.write_text(token + "\n")
    return {
        "schema_version": 1,
        "active_env": "stage",
        "connections": {
            "stage": {
                "transport": "https",
                "api_url": api_url,
                "credential_source": {
                    "kind": "token_file",
                    "path": str(token_file),
                },
            },
        },
    }


def _stage_entry(config):
    return config["connections"]["stage"]


class TestContractValidation:
    def test_https_config_validates(self, tmp_path):
        payload = _https_config(tmp_path)
        payload["temp_root"] = str(tmp_path)
        assert validate_payload(payload) == []

    def test_https_requires_api_url_and_token_kind(self, tmp_path):
        payload = _https_config(tmp_path, api_url="")
        _stage_entry(payload)["credential_source"] = {
            "kind": "dsn_file",
            "path": "/x",
        }
        codes = {issue.code for issue in validate_payload(payload)}
        assert "api_url_required" in codes
        assert "https_credential_kind_invalid" in codes

    def test_token_file_requires_path(self, tmp_path):
        payload = _https_config(tmp_path)
        _stage_entry(payload)["credential_source"] = {"kind": "token_file"}
        codes = {issue.code for issue in validate_payload(payload)}
        assert "credential_token_file_path_required" in codes
