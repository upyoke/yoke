"""CLI recovery text and secret redaction require no server or database."""

import io
import sys

import pytest

from yoke_cli.commands import connect
from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.config import teammate_invite_redemption as redemption
from yoke_cli.config import team_server_authorization as team
from yoke_contracts.bounded_json_http import BoundedJsonHttpStatusError

ORIGIN = "https://team.example"
FLAG = "--invite-code-stdin"


@pytest.mark.parametrize(
    "reason",
    (
        "invite_code_invalid invite_expired invite_revoked invite_consumed "
        "invite_actor_disabled invite_machine_owned machine_identity_required "
        "result_unavailable invite_email_required invite_local_universe "
        "invite_reissue_disabled_actor oidc_misconfigured "
        "authorization_invite_redeem_rate_limited"
    ).split(),
)
def test_cli_refusal_recovery(monkeypatch, capsys, reason):
    monkeypatch.setattr(team, "sign_in_methods", lambda _: team.SignInMethods(True, False))
    code = "yinv_" + "a" * 32
    monkeypatch.setattr(auth, "_machine_identity", lambda: {
        "machine_id": "test-machine", "machine_name": "Test laptop",
    })

    def refuse(*args, **kwargs):
        raise BoundedJsonHttpStatusError(
            429 if "rate_limited" in reason else 409,
            {"error": reason, "message": code + " raw-credential"},
        )

    monkeypatch.setattr(redemption, "request_json", refuse)
    monkeypatch.setattr(sys, "stdin", io.StringIO(code))
    assert connect.connect([ORIGIN, FLAG, "--json"]) == 1
    output = capsys.readouterr()
    assert reason + ":" in output.err and redemption._RECOVERY[reason] in output.err
    assert code not in output.out + output.err
    assert "raw-credential" not in output.err


