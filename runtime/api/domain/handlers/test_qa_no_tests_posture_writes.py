"""Handler coverage for attesting and clearing a project's no-tests posture."""

from __future__ import annotations

import unittest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.verification_posture import (
    POSTURE_ATTESTED_NO_TESTS,
    POSTURE_UNDECIDED,
)
from yoke_core.domain.handlers import qa_no_tests_posture_writes as writes
from yoke_core.domain.handlers import qa_registered_command_writes as command_writes
from runtime.api.fixtures.pg_testdb import test_database

_REASON = "pre-code idea repository; nothing to run yet"


def _request(function: str, payload: dict, *, target_kind: str = "global"):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


def _attest(payload: dict | None = None, **kwargs):
    return writes.handle_no_tests_attest(
        _request(
            "qa.no_tests.attest",
            payload if payload is not None else {"project": "yoke", "reason": _REASON},
            **kwargs,
        )
    )


class TestNoTestsPostureWrites(unittest.TestCase):
    def test_attest_records_the_posture_and_its_reason(self) -> None:
        with test_database():
            outcome = _attest()

        self.assertTrue(outcome.primary_success, outcome.error)
        result = outcome.result_payload["result"]
        self.assertEqual(result["posture"], POSTURE_ATTESTED_NO_TESTS)
        self.assertEqual(result["reason"], _REASON)

    def test_attest_retires_a_registered_command_and_blocks_re_registration(
        self,
    ) -> None:
        with test_database():
            command_writes.handle_registered_command_set(
                _request(
                    "qa.registered_command.set",
                    {
                        "project": "yoke",
                        "scope": "quick",
                        "command": "python3 -m pytest",
                    },
                )
            )
            attested = _attest()
            self.assertEqual(
                attested.result_payload["result"]["retired_plans"],
                ["registered-command-quick"],
            )

            refused = command_writes.handle_registered_command_set(
                _request(
                    "qa.registered_command.set",
                    {
                        "project": "yoke",
                        "scope": "quick",
                        "command": "python3 -m pytest",
                    },
                )
            )

        self.assertFalse(refused.primary_success)
        self.assertEqual(refused.error.code, "incompatible")
        self.assertIn("no-tests clear", refused.error.message)

    def test_clear_returns_the_project_to_undecided(self) -> None:
        with test_database():
            _attest()
            outcome = writes.handle_no_tests_clear(
                _request(
                    "qa.no_tests.clear",
                    {"project": "yoke", "reason": "the suite now exists"},
                )
            )

        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(
            outcome.result_payload["result"]["posture"], POSTURE_UNDECIDED
        )

    def test_a_reasonless_attestation_is_refused_before_it_reaches_the_db(
        self,
    ) -> None:
        outcome = _attest({"project": "yoke"})

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_an_unknown_project_is_refused_by_name(self) -> None:
        with test_database():
            outcome = _attest({"project": "no-such-project", "reason": _REASON})

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")

    def test_an_item_target_is_refused(self) -> None:
        outcome = _attest(target_kind="item")

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")
