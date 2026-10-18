"""Guardrail naming results that carry a one-time credential.

Dispatch never ledgers such a result for replay and never copies it into a
debug capture; the stored-receipt scrub uses the same name as its marker.
"""

from __future__ import annotations


ONE_TIME_SECRET_GUARDRAIL = "one_time_secret_result"
