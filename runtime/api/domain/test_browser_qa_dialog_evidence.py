"""Page dialog observations reach the case step log on pass and failure."""

from unittest.mock import patch

import pytest

from yoke_core.domain.browser_qa_steps import _execute_step


@pytest.mark.parametrize("success", [True, False])
def test_step_logs_observed_dialogs(success: bool) -> None:
    response = {
        "success": True,
        "data": {
            "success": success,
            "dialogs": [{"type": "confirm", "message": "Remove?", "accepted": success}],
        },
    }
    with (
        patch("yoke_core.domain.browser_client.daemon_running", return_value=True),
        patch("yoke_core.domain.browser_client.execute_step", return_value=response),
        patch("yoke_core.domain.browser_qa_sign_in_evidence.current_google_account"),
        patch("yoke_core.domain.browser_qa._log") as log,
    ):
        found = _execute_step(
            {"action": "click", "target": "#remove"},
            "https://example.test",
            "/tmp",
            "page",
        )
    assert found == response
    log.assert_called_once()
    message = log.call_args.args[0]
    assert '"type": "confirm"' in message
    assert '"message": "Remove?"' in message
    assert f'"accepted": {str(success).lower()}' in message
