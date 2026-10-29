"""Send feedback directly to Yoke without forwarding universe credentials."""

import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request

from yoke_cli.transport.https_urlopen import open_no_redirect
from yoke_contracts.engine_version import local_handshake_version

FEEDBACK_URL = "https://app.upyoke.com/api/orgs/upyoke/v1/feedback"
FEEDBACK_URL_SETTING = "YOKE_FEEDBACK_URL"


def send_feedback(*, category, evidence, metadata, agent, json_mode=False):
    payload = {"category": category, "evidence": evidence, "agent": agent or "unknown",
               **{key: metadata.get(key) or "" for key in
                  ("reporter_email", "yoke_version", "universe_fingerprint")}}
    url = os.environ.get(FEEDBACK_URL_SETTING) or FEEDBACK_URL
    try:
        request = Request(url, data=json.dumps(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json",
                                   "User-Agent": "yoke-cli/" + (local_handshake_version() or "unknown")})
        with open_no_redirect(request, timeout=20) as response:
            if response.status not in (200, 201):
                raise ValueError(f"HTTP {response.status}")
            result = json.load(response)
            if not result.get("entry_id"):
                raise ValueError("receiver did not return a note receipt")
    except Exception as exc:
        detail = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        print(f"feedback_delivery_failed: {detail}; retry yoke feedback --to yoke with the same category and evidence.", file=sys.stderr)
        print("Evidence retained for retry:\n" + evidence, file=sys.stderr)
        return 1
    print(json.dumps({"success": True, "destination": "yoke", **result}) if json_mode
          else f"Feedback note {result['entry_id']} delivered to Yoke.")
    return 0
