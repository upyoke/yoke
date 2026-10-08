"""Host-local ephemeral runner registration and execution loop."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webapp_runner_fleet_config import WebappRunnerFleetArgs


def _runner_cycle_script(
    *,
    args: WebappRunnerFleetArgs,
    region: str,
    github_broker_function: str,
) -> str:
    """Return the host-local loop that rearms one ephemeral runner per job."""
    labels_csv = ",".join(args.runner_labels)
    return f"""#!/bin/bash
set -euo pipefail
REGION={shlex.quote(region)}
GITHUB_WEB_URL={shlex.quote(args.github_web_url)}
GITHUB_REPO={shlex.quote(args.github_repo)}
RUNNER_LABELS={shlex.quote(labels_csv)}
GITHUB_BROKER_FUNCTION={shlex.quote(github_broker_function)}
RUNNER_NAME_PREFIX={shlex.quote(args.deploy_namespace + "-github-actions-")}
STATE_DIR=/var/lib/yoke-runner-fleet
ARCHIVE=/opt/actions-runner/actions-runner.tar.gz
WORK_ROOT=/opt/actions-runner/jobs
INITIAL_REGISTRATION="${{STATE_DIR}}/initial-registration.json"
CYCLE_DIR=""

instance_id() {{
  local token
  token="$(curl -fsS -X PUT \\
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600' \\
    http://169.254.169.254/latest/api/token)"
  curl -fsS -H "X-aws-ec2-metadata-token: ${{token}}" \\
    http://169.254.169.254/latest/meta-data/instance-id
}}
INSTANCE_ID="$(instance_id)"
RUNNER_NAME="${{RUNNER_NAME_PREFIX}}${{INSTANCE_ID}}"

github_broker() {{
  local action="$1"
  local payload response_file function_error
  payload="$(jq -cn \\
    --arg action "${{action}}" \\
    --arg instance_id "${{INSTANCE_ID}}" \\
    '{{action:$action,instance_id:$instance_id}}')"
  response_file="$(mktemp /tmp/yoke-runner-broker.XXXXXX)"
  if ! function_error="$(aws lambda invoke \\
      --function-name "${{GITHUB_BROKER_FUNCTION}}" \\
      --cli-binary-format raw-in-base64-out \\
      --payload "${{payload}}" \\
      --query FunctionError --output text --region "${{REGION}}" \\
      "${{response_file}}")"; then
    rm -f "${{response_file}}"
    return 1
  fi
  if [ "${{function_error}}" != "None" ]; then
    cat "${{response_file}}" >&2
    rm -f "${{response_file}}"
    return 1
  fi
  cat "${{response_file}}"
  rm -f "${{response_file}}"
}}

cleanup_cycle() {{
  if [ -n "${{CYCLE_DIR}}" ]; then
    rm -rf "${{CYCLE_DIR}}"
    CYCLE_DIR=""
  fi
}}

cycle_failed() {{
  local rc=$?
  trap - ERR
  cleanup_cycle
  github_broker failed >/dev/null 2>&1 || true
  exit "${{rc}}"
}}
trap cycle_failed ERR

mkdir -p "${{WORK_ROOT}}"
while true; do
  CYCLE_DIR="$(mktemp -d "${{WORK_ROOT}}/cycle.XXXXXX")"
  tar xzf "${{ARCHIVE}}" -C "${{CYCLE_DIR}}"
  registration_file="$(mktemp /tmp/yoke-runner-registration.XXXXXX)"
  if [ -f "${{INITIAL_REGISTRATION}}" ]; then
    mv "${{INITIAL_REGISTRATION}}" "${{registration_file}}"
  else
    github_broker register >"${{registration_file}}"
  fi
  registration_token="$(jq -r '.registration_token // empty' \\
    "${{registration_file}}")"
  rm -f "${{registration_file}}"
  if [ -z "${{registration_token}}" ]; then
    echo "Runner registration response omitted its token" >&2
    exit 1
  fi
  (
    cd "${{CYCLE_DIR}}"
    ./config.sh --unattended --replace --ephemeral \\
      --url "${{GITHUB_WEB_URL}}/${{GITHUB_REPO}}" \\
      --token "${{registration_token}}" --name "${{RUNNER_NAME}}" \\
      --labels "${{RUNNER_LABELS}}" --work _work
  )
  unset registration_token
  github_broker ready >/dev/null
  set +e
  (cd "${{CYCLE_DIR}}" && ./run.sh)
  runner_rc=$?
  set -e
  if [ "${{runner_rc}}" -ne 0 ]; then
    cleanup_cycle
    github_broker failed >/dev/null 2>&1 || true
    exit "${{runner_rc}}"
  fi
  github_broker rearming >/dev/null
  cleanup_cycle
done
"""


def _runner_service_unit() -> str:
    """Return the systemd unit supervising the host-local runner loop."""
    return """[Unit]
Description=Yoke ephemeral GitHub Actions runner loop
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=actions
Group=actions
ExecStart=/usr/local/bin/yoke-runner-cycle
Restart=on-failure
RestartSec=15
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""


__all__ = ["_runner_cycle_script", "_runner_service_unit"]
