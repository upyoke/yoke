"""Project declaration for the machine-relay Doctor health check."""

from yoke_core.engines.doctor_hc_session_relay import (
    TITLE,
    hc_session_relay,
)
from yoke_project_checks._declare import self_project_checks


PROJECT_HEALTH_CHECKS = self_project_checks(
    ("session-relay", TITLE, hc_session_relay),
)


__all__ = ["PROJECT_HEALTH_CHECKS"]
