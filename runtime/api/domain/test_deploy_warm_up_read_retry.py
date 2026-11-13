"""Warm-up absorbs cold read failures without retrying other refusals."""

from unittest import mock

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deploy_warm_up as warm_up
from yoke_core.domain.deploy_pipeline_control_plane import (
    READ_RETRY_BACKOFF_SECONDS,
    READ_RETRY_CODES,
)


def _response(code=None):
    return FunctionCallResponse(
        success=code is None,
        function=warm_up.DEFAULT_WARM_UP_FUNCTION,
        version="v1",
        request_id="warm-read",
        error=FunctionError(code=code, message="cold read") if code else None,
    )


def _run(responses):
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=object(),
        ),
        mock.patch(
            "yoke_cli.transport.https.relay_https", side_effect=responses
        ) as relay,
        mock.patch.object(warm_up, "time") as clock,
        mock.patch.object(warm_up, "_monotonic", side_effect=[0.0, 27.0]),
    ):
        outcome = warm_up.warm_up_environment("prod")
    return outcome, relay, clock.sleep


@pytest.mark.parametrize("code", sorted(READ_RETRY_CODES))
def test_transient_read_recovers_on_the_same_request(code, capsys):
    outcome, relay, sleep = _run([_response(code), _response()])

    assert outcome.ok
    assert outcome.latency_ms == 27000
    assert relay.call_args_list[0] == relay.call_args_list[1]
    sleep.assert_called_once_with(READ_RETRY_BACKOFF_SECONDS[0])
    assert code in capsys.readouterr().err


@pytest.mark.parametrize("code", sorted(READ_RETRY_CODES))
def test_exhausted_reads_stop_after_shared_schedule_with_recovery(code):
    attempts = len(READ_RETRY_BACKOFF_SECONDS) + 1
    outcome, relay, sleep = _run([_response(code)] * attempts)

    assert not outcome.ok
    assert relay.call_count == attempts
    assert sleep.call_args_list == [mock.call(d) for d in READ_RETRY_BACKOFF_SECONDS]
    assert code in outcome.detail
    assert "Inspect the target connection and server" in outcome.detail


@pytest.mark.parametrize("code", ["permission_denied", "invalid_payload", "busy"])
def test_other_refusals_fail_without_retry(code):
    outcome, relay, sleep = _run([_response(code)])

    assert not outcome.ok
    assert code in outcome.detail
    relay.assert_called_once()
    sleep.assert_not_called()
