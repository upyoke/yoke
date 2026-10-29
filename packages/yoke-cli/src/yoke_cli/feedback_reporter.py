"""Best-effort reporter metadata without exposing login credentials."""

import base64
import json
import os
from pathlib import Path
import subprocess

from yoke_cli.commands._helpers import build_actor, ensure_handlers_loaded
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.api.function_call import TargetRef


def harness_email(home=None):
    home = Path(home) if home else Path.home()
    try:
        value = json.loads((home / ".claude.json").read_text()).get("oauthAccount", {}).get("emailAddress")
        if value:
            return value
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
        data = json.loads((codex_home / "auth.json").read_text())
        token = (data.get("tokens") or {}).get("id_token", "")
        claim = token.split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(claim + "=" * (-len(claim) % 4))).get("email")
        if value:
            return value
    except (OSError, ValueError, IndexError, TypeError, AttributeError):
        pass
    # Cursor has no verified portable login-email file; use the checkout next.
    return None


def git_email(checkout=None):
    try:
        result = subprocess.run(["git", "-C", str(checkout or Path.cwd()), "config", "user.email"],
                                text=True, capture_output=True, timeout=5)
        email = result.stdout.strip() if result.returncode == 0 else ""
        return email if email and email != "yoke@example.invalid" else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def reporter_context(session_id=None):
    context = {}
    try:
        ensure_handlers_loaded()
        response = call_dispatcher(function_id="sessions.identity", target=TargetRef(kind="global"),
                                   payload={}, actor=build_actor(session_id=session_id), timeout_s=5, max_attempts=1)
        if response.success:
            context = {key: response.result.get(key) for key in
                       ("reporter_email", "yoke_version", "universe_fingerprint")}
    except Exception:
        # Feedback still works when the sender's control plane cannot be reached.
        pass
    context["reporter_email"] = context.get("reporter_email") or harness_email() or git_email()
    return context
