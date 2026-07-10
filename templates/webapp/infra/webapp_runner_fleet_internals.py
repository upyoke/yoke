# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_fleet_internals.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pure-value helpers for the runner-fleet Pulumi stack.

Holds the IAM policy-document builders, the AMI/runner architecture helpers,
the EC2 UserData builder, and the webhook Lambda source. Split out of
``webapp_runner_fleet_stack`` so each module stays under the authored-file line
limit. Everything here returns plain strings consumed as resource inputs.

The Function-URL dynamic provider deliberately stays in
``webapp_runner_fleet_stack``: Pulumi serializes the provider object into stack
state keyed by its defining module, so relocating it would rewrite ``__provider``
and force a no-op resource update on every deploy.
"""

from __future__ import annotations

import base64
import json
import shlex
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webapp_runner_fleet_config import WebappRunnerFleetArgs


def _assume_role_policy(service: str) -> str:
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": service},
            "Action": "sts:AssumeRole",
        }],
    })


def _ami_arch(architecture: str) -> str:
    return "arm64" if architecture.lower() == "arm64" else "amd64"


def _runner_arch(architecture: str) -> str:
    return "arm64" if architecture.lower() == "arm64" else "x64"


def _user_data(
    *,
    args: WebappRunnerFleetArgs,
    region: str,
    github_broker_function: str,
) -> str:
    labels_csv = ",".join(args.runner_labels)
    runner_arch = _runner_arch(args.architecture)
    script = f"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
PROJECT={shlex.quote(args.deploy_namespace)}
REGION={shlex.quote(region)}
GITHUB_REPO={shlex.quote(args.github_repo)}
GITHUB_WEB_URL={shlex.quote(args.github_web_url)}
RUNNER_LABELS={shlex.quote(labels_csv)}
GITHUB_BROKER_FUNCTION={shlex.quote(github_broker_function)}
RUNNER_ARCH={shlex.quote(runner_arch)}
PREFIX="${{PROJECT}}-github-actions"
BOOTSTRAP_FILE=""

cleanup_bootstrap() {{
  if [ -n "${{BOOTSTRAP_FILE}}" ]; then
    rm -f "${{BOOTSTRAP_FILE}}"
    BOOTSTRAP_FILE=""
  fi
}}

bootstrap_failed() {{
  local rc=$?
  trap - ERR
  cleanup_bootstrap
  if [ -n "${{INSTANCE_ID:-}}" ] && command -v aws >/dev/null 2>&1; then
    github_broker "{{\"action\":\"failed\",\"instance_id\":\"${{INSTANCE_ID}}\"}}" \
      >/dev/null 2>&1 || true
  fi
  exit "${{rc}}"
}}
trap bootstrap_failed ERR

apt-get update
# python3-venv: nested venv + ensurepip (test_pep503 / installer venv tests);
# postgresql-client: pg_dump (DB-dump tests); build-essential/python3-dev:
# C-extension builds. Without these the CI test suite hits 127/ModuleNotFound.
apt-get install -y ca-certificates curl git jq python3 python3-pip python3-venv python3-dev build-essential postgresql-client sudo unzip
apt-get install -y docker.io docker-buildx || apt-get install -y docker.io
AWSCLI_ARCH="aarch64"
if [ "$(dpkg --print-architecture)" = "amd64" ]; then
  AWSCLI_ARCH="x86_64"
fi
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${{AWSCLI_ARCH}}.zip" \
  -o /tmp/awscliv2.zip
rm -rf /tmp/aws
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install --update
rm -rf /tmp/aws /tmp/awscliv2.zip
systemctl enable --now docker
id actions >/dev/null 2>&1 || useradd -m -s /bin/bash actions
usermod -aG docker actions || true; printf 'actions ALL=(ALL) NOPASSWD:ALL\n' >/etc/sudoers.d/actions; chmod 440 /etc/sudoers.d/actions
mkdir -p /opt/actions-runner /var/lib/yoke-runner-fleet
chown -R actions:actions /opt/actions-runner

env HOME=/root PULUMI_HOME=/root/.pulumi sh -c 'curl -fsSL https://get.pulumi.com | sh'
PULUMI_BIN=/root/.pulumi/bin/pulumi; [ -x "$PULUMI_BIN" ] || PULUMI_BIN=/.pulumi/bin/pulumi; install -m 0755 "$PULUMI_BIN" /usr/bin/pulumi; ln -sf /usr/bin/pulumi /usr/local/bin/pulumi
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh || true

IMDS_TOKEN="$(curl -fsS -X PUT \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600' \
  http://169.254.169.254/latest/api/token)"
INSTANCE_ID="$(curl -fsS -H "X-aws-ec2-metadata-token: ${{IMDS_TOKEN}}" \
  http://169.254.169.254/latest/meta-data/instance-id)"
HOST_PREFIX="${{PREFIX}}-${{INSTANCE_ID}}"

github_broker() {{
  local payload="$1"
  local response_file
  local function_error
  response_file="$(mktemp /tmp/yoke-runner-broker.XXXXXX)"
  if ! function_error="$(aws lambda invoke \
      --function-name "${{GITHUB_BROKER_FUNCTION}}" \
      --cli-binary-format raw-in-base64-out \
      --payload "${{payload}}" \
      --query FunctionError --output text --region "${{REGION}}" \
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

BOOTSTRAP_FILE="$(mktemp /run/yoke-runner-bootstrap.XXXXXX)"
chmod 600 "${{BOOTSTRAP_FILE}}"
github_broker "{{\"action\":\"bootstrap\",\"instance_id\":\"${{INSTANCE_ID}}\"}}" \
  >"${{BOOTSTRAP_FILE}}"
RUNNER_DOWNLOAD_URL="$(jq -r '.download_url // empty' "${{BOOTSTRAP_FILE}}")"
if [ -z "${{RUNNER_DOWNLOAD_URL}}" ] || [ "${{RUNNER_DOWNLOAD_URL}}" = "null" ]; then
  echo "Could not resolve actions runner download URL" >&2
  exit 1
fi
dir="/opt/actions-runner/runner"
mkdir -p "${{dir}}"
chown -R actions:actions "${{dir}}"
sudo -u actions bash -c \
  'cd "$1" && curl -fsSL -o actions-runner.tar.gz "$2" \
   && tar xzf actions-runner.tar.gz && rm actions-runner.tar.gz' \
  _ "${{dir}}" "${{RUNNER_DOWNLOAD_URL}}"
reg_token="$(jq -r '.registration_token // empty' "${{BOOTSTRAP_FILE}}")"
if [ -z "${{reg_token}}" ]; then
  echo "Runner bootstrap omitted its registration token" >&2
  exit 1
fi
sudo -u actions bash -c \
  'cd "$1" && ./config.sh --unattended --replace --ephemeral \
   --url "$2" --token "$3" --name "$4" --labels "$5" --work _work' \
  _ "${{dir}}" "${{GITHUB_WEB_URL}}/${{GITHUB_REPO}}" "${{reg_token}}" \
  "${{HOST_PREFIX}}" "${{RUNNER_LABELS}}"
unset reg_token
cleanup_bootstrap
github_broker "{{\"action\":\"ready\",\"instance_id\":\"${{INSTANCE_ID}}\"}}" \
  >/dev/null
(cd "${{dir}}" && ./svc.sh install actions && ./svc.sh start)
trap - ERR
"""
    return base64.b64encode(script.encode("utf-8")).decode("ascii")


def _webhook_lambda_code() -> str:
    return textwrap.dedent(
        r'''
        import base64, boto3, hmac, hashlib, json, os, time

        autoscaling = boto3.client("autoscaling")
        ssm = boto3.client("ssm")
        _webhook_secret_cache = None

        def _webhook_secret():
            global _webhook_secret_cache
            if _webhook_secret_cache is None:
                _webhook_secret_cache = ssm.get_parameter(
                    Name=os.environ["WEBHOOK_SECRET_PARAMETER"],
                    WithDecryption=True,
                )["Parameter"]["Value"].encode("utf-8")
            return _webhook_secret_cache

        def _response(status, body):
            return {"statusCode": status, "body": json.dumps(body)}

        def _header(headers, name):
            wanted = name.lower()
            for key, value in (headers or {}).items():
                if key.lower() == wanted:
                    return value
            return ""

        def _body(event):
            raw = event.get("body") or ""
            if event.get("isBase64Encoded"):
                return base64.b64decode(raw)
            return raw.encode("utf-8")

        def handler(event, _context):
            body = _body(event)
            headers = event.get("headers") or {}
            expected = "sha256=" + hmac.new(
                _webhook_secret(), body, hashlib.sha256,
            ).hexdigest()
            signature = _header(headers, "X-Hub-Signature-256")
            if not hmac.compare_digest(signature, expected):
                return _response(401, {"ok": False, "error": "bad_signature"})
            event_name = _header(headers, "X-GitHub-Event")
            if event_name == "ping":
                return _response(200, {"ok": True, "action": "pong"})
            if event_name != "workflow_job":
                return _response(200, {"ok": True, "action": "ignored"})
            payload = json.loads(body.decode("utf-8"))
            repository = payload.get("repository") or {}
            if (
                str(repository.get("id") or "")
                != os.environ["EXPECTED_REPOSITORY_ID"]
                or str(repository.get("full_name") or "").casefold()
                != os.environ["EXPECTED_REPOSITORY"].casefold()
            ):
                return _response(200, {"ok": True, "action": "wrong_repository"})
            action = str(payload.get("action") or "")
            job = payload.get("workflow_job") or {}
            labels = {str(label).lower() for label in job.get("labels") or []}
            required = {
                label.strip().lower()
                for label in os.environ["REQUIRED_LABELS"].split(",")
                if label.strip()
            }
            if not required.issubset(labels):
                return _response(200, {"ok": True, "action": "ignored"})
            if action in {"in_progress", "completed"}:
                runner_name = str(job.get("runner_name") or "")
                prefix = os.environ["RUNNER_PREFIX"]
                instance_id = runner_name.removeprefix(prefix)
                if (
                    not runner_name.startswith(prefix)
                    or not instance_id.startswith("i-")
                    or not all(c in "0123456789abcdef" for c in instance_id[2:])
                    or len(instance_id) not in {10, 19}
                ):
                    return _response(200, {"ok": True, "action": "ignored"})
                parameter_name = (
                    os.environ["RUNNER_COMPLETION_PARAMETER"]
                    if action == "completed"
                    else os.environ["RUNNER_PROGRESS_PARAMETER"]
                )
                ssm.put_parameter(
                    Name=parameter_name,
                    Type="String",
                    Value=json.dumps({
                        "action": action,
                        "runner_name": runner_name,
                        "job_id": str(job.get("id") or ""),
                        "at": int(time.time()),
                    }, separators=(",", ":")),
                    Overwrite=True,
                )
                return _response(202, {"ok": True, "action": "recorded"})
            if action != "queued":
                return _response(200, {"ok": True, "action": "ignored"})
            delivery = _header(headers, "X-GitHub-Delivery") or "unknown"
            ssm.put_parameter(
                Name=os.environ["QUEUE_ACTIVITY_PARAMETER"],
                Type="String",
                Value=f"{time.time_ns()}:{delivery}",
                Overwrite=True,
            )
            autoscaling.set_desired_capacity(
                AutoScalingGroupName=os.environ["ASG_NAME"],
                DesiredCapacity=1,
                HonorCooldown=False,
            )
            return _response(202, {"ok": True, "action": "started"})
        '''
    ).strip() + "\n"
