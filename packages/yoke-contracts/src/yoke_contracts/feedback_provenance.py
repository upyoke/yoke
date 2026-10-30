"""Required feedback identity shapes shared by every writer."""

import re
from yoke_contracts.release_version import reporting_version_shape
from yoke_contracts.timestamps import parse_instant
from yoke_contracts.refusal_recovery import compose_refusal

UPGRADE_RECOVERY = "Upgrade Yoke (`yoke core upgrade`), then retry."


class FeedbackIdentityError(ValueError):
    def __init__(self, code):
        self.code = code
        self.recovery = UPGRADE_RECOVERY
        super().__init__(compose_refusal(code, recovery=self.recovery))


def validate_feedback_identity(*, yoke_version, universe_fingerprint, agent):
    for name, value in (("version", yoke_version),
                        ("fingerprint", universe_fingerprint), ("agent", agent)):
        if value is None or value == "":
            raise FeedbackIdentityError(f"feedback_{name}_missing")
        try:
            if not isinstance(value, str):
                raise ValueError("expected text")
            if name == "version":
                reporting_version_shape(value)
            elif name == "fingerprint":
                slug, separator, timestamp = value.partition("@")
                if not separator or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
                    raise ValueError("expected slug@timestamp")
                parse_instant(timestamp)
            elif not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", value) or value == "unknown":
                raise ValueError("expected an agent name")
        except (ValueError, TypeError):
            raise FeedbackIdentityError(f"feedback_{name}_invalid") from None
