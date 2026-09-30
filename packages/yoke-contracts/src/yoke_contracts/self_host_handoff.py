"""Private host/container bootstrap transport and its bounded secret schema."""

from dataclasses import dataclass

HANDOFF_SOCKET = "/run/yoke-bootstrap.sock"
HANDOFF_TIMEOUT_SECONDS = 180
HANDOFF_MAX_BYTES = 1 << 20
HANDOFF_ACK = b"saved\n"
DB_PASSWORD_RUNTIME_PATH = "/run/yoke-db-bootstrap/password"
DB_PASSWORD_INGRESS = f"umask 077; cat > {DB_PASSWORD_RUNTIME_PATH}.tmp && mv {DB_PASSWORD_RUNTIME_PATH}.tmp {DB_PASSWORD_RUNTIME_PATH}"
HANDOFF_CLIENT_MODULE = "yoke_core.tools.self_host_handoff"


@dataclass(frozen=True)
class SecretSpec:
    env_name: str
    host_name: str
    runtime_name: str
    required: bool = False
    max_bytes: int = 1 << 16


CORE_SECRETS = (
    SecretSpec("YOKE_PG_DSN_FILE", "dsn", "yoke-db-dsn", True),
    SecretSpec(
        "YOKE_OIDC_CLIENT_SECRET_FILE", "oidc-client-secret", "yoke-oidc-client-secret"
    ),
    SecretSpec(
        "YOKE_GITHUB_APP_PRIVATE_KEY_FILE",
        "github-app-private-key.pem",
        "yoke-github-app-private-key",
    ),
)
