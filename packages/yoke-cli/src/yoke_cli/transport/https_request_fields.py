"""Declared secret payload fields for HTTPS relay response scrubbing."""

from collections.abc import Mapping

_SENSITIVE_PAYLOAD_PATHS_BY_FUNCTION: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "github_actions.secret.set": (("value",),),
    "projects.capability_secret.set": (("value",),),
    "projects.pulumi_state.checkpoint_import": (
        ("secrets_provider",),
        ("encrypted_key",),
    ),
}
