"""Check a full day of production overview timings after a release receipt."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import re
import subprocess


class EvidenceUnavailable(ValueError):
    """A complete production observation window is not available."""


def read_json(arguments):
    result = subprocess.run(arguments, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def window_start(run_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise EvidenceUnavailable("invalid run id; use the deployment run's exact id")
    result = read_json(
        [
            "yoke",
            "db",
            "read",
            "SELECT completed_at FROM deployment_stage_receipts "
            f"WHERE run_id='{run_id}' AND status='ready' AND target_name='prod' "
            "ORDER BY completed_at DESC LIMIT 1",
            "--format",
            "json",
        ]
    )
    if result.get("truncated") or not result.get("rows"):
        raise EvidenceUnavailable(
            "production ready receipt missing; finish deployment first"
        )
    return datetime.fromisoformat(result["rows"][0][0].replace("Z", "+00:00"))


def evaluate(events):
    records = []
    for event in events:
        message = event["message"]
        prefix = "Deployment start timing: "
        if prefix not in message:
            continue
        row = json.loads(message.split(prefix, 1)[1])
        if row.get("step") == "shipping_overview":
            records.append(row)
    starts = [row for row in records if row.get("phase") == "start"]
    ends = [row for row in records if row.get("phase") == "end"]
    if not ends or len(starts) != len(ends):
        raise EvidenceUnavailable(
            "missing overview timings; collect a complete traffic window"
        )
    # Empty overviews must not dilute the slower, populated release reads.
    samples = [float(row["elapsed_ms"]) for row in ends if row.get("member_count")]
    if not samples:
        raise EvidenceUnavailable(
            "no populated overview traffic; observe real release reads"
        )
    failures = [row for row in ends if row.get("outcome") != "ok"]
    p95 = sorted(samples)[math.ceil(len(samples) * 0.95) - 1]
    summary = {
        "overview_count": len(ends),
        "populated_count": len(samples),
        "populated_p95_ms": p95,
        "failed_count": len(failures),
    }
    if failures or p95 >= 5000:
        raise EvidenceUnavailable(
            f"overview latency failed: {json.dumps(summary)}; inspect QA acceptance timings and repair"
        )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        start = window_start(args.run_id)
        end = start + timedelta(hours=24)
        if datetime.now(timezone.utc) < end + timedelta(minutes=5):
            raise EvidenceUnavailable(
                f"observation window incomplete; retry after {end.isoformat()} plus five minutes for logs"
            )
        events = []
        token = None
        while True:
            command = [
                "yoke",
                "aws",
                "exec",
                "--project",
                "platform",
                "--",
                "logs",
                "filter-log-events",
                "--log-group-name",
                "/yoke/prod/core",
                "--start-time",
                str(int(start.timestamp() * 1000)),
                "--end-time",
                str(int(end.timestamp() * 1000)),
                "--filter-pattern",
                '"shipping_overview"',
                "--output",
                "json",
                "--no-paginate",
            ]
            if token:
                command += ["--next-token", token]
            page = read_json(command)
            events.extend(page.get("events", []))
            next_token = page.get("nextToken")
            if not next_token:
                break
            if next_token == token:
                raise EvidenceUnavailable(
                    "log pagination stalled; retry the complete observation read"
                )
            token = next_token
        print(
            json.dumps(
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    **evaluate(events),
                },
                sort_keys=True,
            )
        )
    except (
        EvidenceUnavailable,
        subprocess.CalledProcessError,
        ValueError,
        KeyError,
        OSError,
    ) as exc:
        parser.exit(
            1,
            f"overview_latency_evidence_unavailable: {exc}; "
            "verify the controller CLI and production log-read access, then retry "
            "the complete observation window\n",
        )


if __name__ == "__main__":
    main()
