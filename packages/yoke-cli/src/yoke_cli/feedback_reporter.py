"""Required feedback identity and best-effort reporter email."""

import base64
import json
import os
from pathlib import Path
import subprocess

from yoke_cli.commands._helpers import build_actor, ensure_handlers_loaded
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.harness_sandbox_recovery import running_harness_family
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_cli.transport.json_error_safety import safe_diagnostic_text


def harness_email(harness=None, home=None):
    home = Path(home) if home else Path.home()
    try:
        if harness not in ("claude", "claude-code"):
            raise ValueError("not the active harness")
        value = json.loads((home / ".claude.json").read_text()).get("oauthAccount", {}).get("emailAddress")
        if value:
            return value
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if harness == "cursor":
        try:
            return json.loads((home / ".cursor/cli-config.json").read_text()).get("authInfo", {}).get("email") or None
        except (OSError, ValueError, TypeError, AttributeError):
            return None
    try:
        if harness != "codex":
            return None
        codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
        data = json.loads((codex_home / "auth.json").read_text())
        token = (data.get("tokens") or {}).get("id_token", "")
        claim = token.split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(claim + "=" * (-len(claim) % 4))).get("email")
        if value:
            return value
    except (OSError, ValueError, IndexError, TypeError, AttributeError):
        pass
    return None



def git_email(checkout=None):
    try:
        result = subprocess.run(["git", "-C", str(checkout or Path.cwd()), "config", "user.email"],
                                text=True, capture_output=True, timeout=5)
        email = result.stdout.strip() if result.returncode == 0 else ""
        return email if email and email != "yoke@example.invalid" else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _bound_fingerprint():
    from yoke_cli.config import machine_config
    from yoke_contracts.machine_config.schema_connections import operating_actor_binding
    try:
        return operating_actor_binding(machine_config.load_config(), machine_config.active_env())[1]
    except Exception:
        return ""


def feedback_provenance(session_id=None):
    """Stamp both destinations once, independently of a registered session."""
    from yoke_contracts.runtime_identity import reporting_version
    from yoke_contracts.session_identity import resolve_actor_role
    from yoke_contracts.feedback_provenance import validate_feedback_identity, FeedbackIdentityError

    context = {}
    server_error = None
    harness = running_harness_family()
    try:
        version = reporting_version()
    except Exception as exc:
        raise ValueError(compose_refusal("feedback_provenance_unavailable: yoke_version",
                                         evaluated=safe_diagnostic_text(str(exc)),
                                         recovery="Reinstall Yoke, then retry.")) from None
    try:
        ensure_handlers_loaded()
        response = call_dispatcher(function_id="feedback.provenance.get", target=TargetRef(kind="global"),
                                   payload={}, actor=build_actor(session_id=session_id), timeout_s=5, max_attempts=1)
        if response.success:
            context = response.result or {}
        elif response.error and response.error.code == "function_version_skew":
            server_error = response.error
    except Exception:
        pass
    metadata = {
        "yoke_version": version,
        "universe_fingerprint": context.get("universe_fingerprint") or _bound_fingerprint(),
        "agent": resolve_actor_role() or harness or "terminal",
        "reporter_email": context.get("actor_email") or harness_email(harness) or git_email(),
    }
    try:
        validate_feedback_identity(**{k: metadata[k] for k in ("yoke_version", "universe_fingerprint", "agent")})
    except FeedbackIdentityError as exc:
        field = {"version": "yoke_version", "fingerprint": "universe_fingerprint", "agent": "agent"}[exc.code.split("_")[1]]
        recovery = "reinstall Yoke" if field == "yoke_version" else "run yoke env use <env> or yoke connect"
        raise ValueError(compose_refusal(f"feedback_provenance_unavailable: {field}",
                                         recovery=f"{recovery}, then retry.")) from None
    if server_error is not None:
        metadata["server_error"] = server_error
    return metadata
