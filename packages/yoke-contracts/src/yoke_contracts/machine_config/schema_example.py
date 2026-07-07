"""Code-owned example payload for `yoke config example`.

Sibling of :mod:`machine_config_contract` (split under the authored-file
cap); the contract module re-exports both functions so callers keep
importing from the contract front door. Constants resolve lazily from
the contract at call time — no import cycle.
"""

from __future__ import annotations

import copy
import json
from typing import Any


def canonical_example_payload() -> dict[str, Any]:
    """Return the code-owned example payload for ``yoke config example``."""
    return copy.deepcopy({
        "schema_version": _contract().SCHEMA_VERSION,
        "active_env": "prod",
        "connections": {
            "prod": {
                "transport": _contract().TRANSPORT_HTTPS,
                _contract().PROD_FLAG_KEY: True,
                "api_url": "https://api.upyoke.com",
                "credential_source": {
                    "kind": "token_file",
                    "path": "~/.yoke/secrets/prod.token",
                },
            },
            "source-dev-admin": {
                "transport": _contract().DEFAULT_TRANSPORT,
                _contract().PROD_FLAG_KEY: False,
                "credential_source": {
                    "kind": "dsn_file",
                    "path": "~/.yoke/secrets/source-dev-admin.dsn",
                },
                "postgres": {
                    "host": "127.0.0.1",
                    "port": 6547,
                    "tunnel": {
                        "kind": "ssh",
                        "bastion": "ubuntu@bastion.example.com",
                        "identity_file": "~/.ssh/example-bastion.pem",
                        "remote_host": "aurora.example.internal",
                        "remote_port": 5432,
                    },
                },
                "authority": {
                    "kind": "aws_aurora_postgres",
                    "infra_dir": "infra/pulumi/yoke-cloud",
                    "location": {
                        "stack": "yoke-prod",
                        "region": "us-east-1",
                        "database_name": "yoke_prod",
                    },
                },
            },
            "stage": {
                "transport": _contract().TRANSPORT_HTTPS,
                _contract().PROD_FLAG_KEY: False,
                "api_url": "https://api.stage.upyoke.com",
                "credential_source": {
                    "kind": "token_file",
                    "path": "~/.yoke/secrets/stage.token",
                },
            },
        },
        "temp_root": _contract().DEFAULT_TEMP_ROOT,
        "cache_dir": _contract().DEFAULT_CACHE_ROOT,
        "github": {
            "api_url": _contract().DEFAULT_GITHUB_API_URL,
            "credential_source": {
                "kind": "token_file",
                "path": "~/.yoke/secrets/github.token",
            },
        },
        "projects": {
            "/Users/example/yoke": {
                "project_id": 1,
                "board": {"render_path": _contract().DEFAULT_BOARD_PATH, "scope": "yoke"},
            },
        },
        "settings": {},
    })

def canonical_example_text() -> str:
    return json.dumps(canonical_example_payload(), indent=2) + "\n"



def _contract():
    from yoke_contracts.machine_config import schema as machine_config_contract
    return machine_config_contract
