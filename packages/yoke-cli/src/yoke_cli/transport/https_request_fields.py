"""Registered request fields distinguish credentials from public proof identifiers."""

import re
from collections.abc import Mapping

_SENSITIVE_KEY_WORDS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passphrase",
        "secret",
        "secrets",
        "token",
        "tokens",
    }
)
_CONTEXT_VALUE_KEYS = frozenset({"content", "data", "plaintext", "value"})
_CONTEXT_NAME_KEYS = frozenset({"field", "key", "name"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_WORD = re.compile(r"[^a-z0-9]+")

# Some registered request schemas deliberately use a generic field name for
# sensitive material.  Key-name heuristics cannot classify these values: an
# Actions secret called ``DATABASE_URL`` still travels in ``payload.value``.
# Keep those exceptions bound to the exact function id and payload path so a
# similarly shaped non-secret operation (for example, an Actions variable)
# remains visible in ordinary responses.
_SENSITIVE_PAYLOAD_PATHS_BY_FUNCTION: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "github_actions.secret.set": (("value",),),
}

# These exact request fields are public by contract even when one nested key
# contains a word such as ``credentials``. Pack render values are non-secret
# project settings and are echoed into the checksum-protected source bundle;
# treating an action pin as a secret would rewrite the response content after
# the server calculated its digest.
_PUBLIC_PAYLOAD_FIELDS_BY_FUNCTION: Mapping[str, frozenset[str]] = {
    "packs.bundle.get": frozenset({"render_values"}),
    "packs.bundle.render": frozenset({"render_values"}),
}


_PUBLIC_PAYLOAD_PATHS_BY_FUNCTION = {
    "test_machine.operation.submit": (
        ("payload", "artifacts", "*", "token"),
        ("payload", "checks", "*", "artifact_token"),
    ),
}
