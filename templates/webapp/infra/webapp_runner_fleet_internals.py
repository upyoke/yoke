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
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from webapp_runner_fleet_stack import WebappRunnerFleetArgs


def _assume_role_policy(service: str) -> str:
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": service},
            "Action": "sts:AssumeRole",
        }],
    })


def _inline_policy(actions: Sequence[str]) -> str:
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": list(actions),
            "Resource": "*",
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
    asg_name: str,
    github_token_parameter: str,
) -> str:
    labels_csv = ",".join(args.runner_labels)
    runner_arch = _runner_arch(args.architecture)
    idle_reaper_script = (
        Path(__file__).with_name("webapp_runner_idle_reaper.py").read_text()
    )
    script = f"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
PROJECT={json.dumps(args.deploy_namespace)}
REGION={json.dumps(region)}
GITHUB_REPO={json.dumps(args.github_repo)}
RUNNER_LABELS={json.dumps(labels_csv)}
RUNNER_COUNT={int(args.runner_count)}
IDLE_MINUTES={int(args.idle_shutdown_minutes)}
ASG_NAME={json.dumps(asg_name)}
GITHUB_TOKEN_PARAMETER={json.dumps(github_token_parameter)}
RUNNER_ARCH={json.dumps(runner_arch)}
PREFIX="${{PROJECT}}-github-actions"

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

github_token() {{
  aws ssm get-parameter --with-decryption \
    --name "${{GITHUB_TOKEN_PARAMETER}}" \
    --query Parameter.Value --output text --region "${{REGION}}"
}}

github_api() {{
  curl -fsS -H "Authorization: Bearer ${{GITHUB_TOKEN}}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" "$@"
}}

GITHUB_TOKEN="$(github_token)"
RUNNER_ASSET_PREFIX="actions-runner-linux-${{RUNNER_ARCH}}-"
RUNNER_DOWNLOAD_URL="$(github_api \
  "https://api.github.com/repos/actions/runner/releases/latest" \
  | jq -r --arg prefix "${{RUNNER_ASSET_PREFIX}}" \
      '.assets[] | select(.name | startswith($prefix) and endswith(".tar.gz")) |
       .browser_download_url' | head -n 1)"
if [ -z "${{RUNNER_DOWNLOAD_URL}}" ] || [ "${{RUNNER_DOWNLOAD_URL}}" = "null" ]; then
  echo "Could not resolve actions runner download URL" >&2
  exit 1
fi
github_api "https://api.github.com/repos/${{GITHUB_REPO}}/actions/runners?per_page=100" \
  | jq -r --arg prefix "${{PREFIX}}-" \
      '.runners[] | select(.name | startswith($prefix)) |
       select(.status == "offline") | .id' \
  | while read -r runner_id; do
      [ -n "${{runner_id}}" ] || continue
      github_api -X DELETE \
        "https://api.github.com/repos/${{GITHUB_REPO}}/actions/runners/${{runner_id}}" \
        >/dev/null || true
    done

for i in $(seq 1 "${{RUNNER_COUNT}}"); do
  dir="/opt/actions-runner/runner-${{i}}"
  mkdir -p "${{dir}}"
  chown -R actions:actions "${{dir}}"
  if [ ! -x "${{dir}}/config.sh" ]; then
    sudo -u actions bash -lc \
      "cd '${{dir}}' && curl -fsSL -o actions-runner.tar.gz \
       '${{RUNNER_DOWNLOAD_URL}}' \
       && tar xzf actions-runner.tar.gz && rm actions-runner.tar.gz"
  fi
  reg_token="$(github_api -X POST \
    "https://api.github.com/repos/${{GITHUB_REPO}}/actions/runners/registration-token" \
    | jq -r .token)"
  sudo -u actions bash -lc \
    "cd '${{dir}}' && ./config.sh --unattended --replace \
     --url 'https://github.com/${{GITHUB_REPO}}' --token '${{reg_token}}' \
     --name '${{HOST_PREFIX}}-${{i}}' --labels '${{RUNNER_LABELS}}' --work _work"
  (cd "${{dir}}" && ./svc.sh install actions && ./svc.sh start)
done

cat >/usr/local/bin/yoke-runner-idle-reaper <<'PY'
{idle_reaper_script}
PY
chmod +x /usr/local/bin/yoke-runner-idle-reaper
cat >/etc/systemd/system/yoke-runner-idle-reaper.service <<EOF
[Unit]
Description=Yoke GitHub Actions runner idle reaper

[Service]
Type=oneshot
Environment=REGION=${{REGION}}
Environment=GITHUB_REPO=${{GITHUB_REPO}}
Environment=GITHUB_TOKEN_PARAMETER=${{GITHUB_TOKEN_PARAMETER}}
Environment=ASG_NAME=${{ASG_NAME}}
Environment=HOST_PREFIX=${{HOST_PREFIX}}
Environment=IDLE_MINUTES=${{IDLE_MINUTES}}
Environment=RUNNER_LABELS=${{RUNNER_LABELS}}
ExecStart=/usr/local/bin/yoke-runner-idle-reaper
EOF
cat >/etc/systemd/system/yoke-runner-idle-reaper.timer <<EOF
[Unit]
Description=Run Yoke GitHub Actions runner idle reaper

[Timer]
OnBootSec=5min
OnUnitActiveSec=60s
Unit=yoke-runner-idle-reaper.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now yoke-runner-idle-reaper.timer
"""
    return base64.b64encode(script.encode("utf-8")).decode("ascii")


def _webhook_lambda_code() -> str:
    return textwrap.dedent(
        r'''
        import base64, boto3, hmac, hashlib, json, os

        autoscaling = boto3.client("autoscaling")
        ssm = boto3.client("ssm")

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
            secret = ssm.get_parameter(
                Name=os.environ["WEBHOOK_SECRET_PARAMETER"],
                WithDecryption=True,
            )["Parameter"]["Value"].encode("utf-8")
            expected = "sha256=" + hmac.new(
                secret, body, hashlib.sha256,
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
            if payload.get("action") != "queued":
                return _response(200, {"ok": True, "action": "ignored"})
            job = payload.get("workflow_job") or {}
            labels = {str(label).lower() for label in job.get("labels") or []}
            required = {
                label.strip().lower()
                for label in os.environ["REQUIRED_LABELS"].split(",")
                if label.strip()
            }
            if not required.issubset(labels):
                return _response(200, {"ok": True, "action": "ignored"})
            autoscaling.set_desired_capacity(
                AutoScalingGroupName=os.environ["ASG_NAME"],
                DesiredCapacity=1,
                HonorCooldown=False,
            )
            return _response(202, {"ok": True, "action": "started"})
        '''
    ).strip() + "\n"
