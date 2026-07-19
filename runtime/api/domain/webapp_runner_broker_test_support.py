"""Node and AWS SDK fakes for executable runner broker tests."""

from __future__ import annotations

from pathlib import Path
import textwrap


INFRA_ROOT = (
    Path(__file__).resolve().parents[3]
    / "packs/self-hosted-runners/versions/1.0.0/files/infra"
)


def _module(tmp_path: Path, package: str, source: str) -> None:
    root = tmp_path / f"node_modules/@aws-sdk/{package}"
    root.mkdir(parents=True)
    (root / "package.json").write_text(
        '{"type":"module","exports":"./index.mjs"}\n'
    )
    (root / "index.mjs").write_text(textwrap.dedent(source))


def _write_node_fixture(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"type":"module"}\n')
    _module(tmp_path, "client-secrets-manager", """
        export class GetSecretValueCommand { constructor(input) { this.input = input; } }
        export class SecretsManagerClient {
          async send(command) {
            if (command.input.SecretId !== process.env.GITHUB_PRIVATE_KEY_SECRET_ARN) {
              throw new Error("wrong secret ARN");
            }
            return { SecretString: globalThis.__privateKey };
          }
        }
    """)
    _module(tmp_path, "client-auto-scaling", """
        export class DescribeAutoScalingInstancesCommand {
          constructor(input) { this.input = input; }
        }
        export class SetDesiredCapacityCommand {
          constructor(input) { this.input = input; }
        }
        export class TerminateInstanceInAutoScalingGroupCommand {
          constructor(input) { this.input = input; }
        }
        export class AutoScalingClient {
          async send(command) {
            if (command instanceof DescribeAutoScalingInstancesCommand) {
              if ((command.input.MaxRecords || 50) > 50) {
                throw new Error("DescribeAutoScalingInstances MaxRecords exceeds API limit");
              }
              const configured = globalThis.__activeInstances;
              const instanceIds = configured === false ? [] :
                Array.isArray(configured) ? configured :
                ["i-0123456789abcdef0"];
              const active = instanceIds.map((InstanceId) => ({
                InstanceId,
                AutoScalingGroupName: process.env.RUNNER_ASG_NAME,
                LifecycleState: "InService",
              }));
              return { AutoScalingInstances: active };
            }
            if (command instanceof SetDesiredCapacityCommand) {
              globalThis.__restoreAttempts = (globalThis.__restoreAttempts || 0) + 1;
              if (globalThis.__restoreErrorOnce) {
                const message = globalThis.__restoreErrorOnce;
                globalThis.__restoreErrorOnce = "";
                throw new Error(message);
              }
              globalThis.__scaled = command.input;
              globalThis.__scaleMutations = (globalThis.__scaleMutations || 0) + 1;
              return {};
            }
            globalThis.__terminationAttempts =
              (globalThis.__terminationAttempts || 0) + 1;
            if (globalThis.__terminationError) {
              throw new Error(globalThis.__terminationError);
            }
            globalThis.__terminated = command.input;
            globalThis.__terminationCalls = globalThis.__terminationCalls || [];
            globalThis.__terminationCalls.push(command.input);
            if (Array.isArray(globalThis.__activeInstances)) {
              globalThis.__activeInstances = globalThis.__activeInstances
                .filter((item) => item !== command.input.InstanceId);
            } else {
              globalThis.__activeInstances = false;
            }
            if (globalThis.__activityOnTerminate) {
              globalThis.__parameters.set(
                process.env.QUEUE_ACTIVITY_PARAMETER,
                globalThis.__activityOnTerminate,
              );
            }
            return {};
          }
        }
    """)
    _module(tmp_path, "client-ec2", """
        export class DescribeInstancesCommand { constructor(input) { this.input = input; } }
        export class EC2Client {
          async send(command) {
            return { Reservations: [{ Instances: [{
              InstanceId: command.input.InstanceIds[0],
              LaunchTime: new Date(Date.now() - 600000),
            }] }] };
          }
        }
    """)
    _module(tmp_path, "client-ssm", """
        class Command { constructor(input) { this.input = input; } }
        export class DeleteParameterCommand extends Command {}
        export class GetParameterCommand extends Command {}
        export class GetParametersByPathCommand extends Command {}
        export class PutParameterCommand extends Command {}
        export class SSMClient {
          async send(command) {
            const values = globalThis.__parameters;
            if (command instanceof GetParametersByPathCommand) {
              return { Parameters: [...values.entries()]
                .filter(([name]) => name.startsWith(command.input.Path + "/"))
                .map(([Name, Value]) => ({ Name, Value })) };
            }
            if (command instanceof GetParameterCommand) {
              if (command.input.Name === process.env.QUEUE_ACTIVITY_PARAMETER &&
                  globalThis.__failQueueReadAfterTerminationOnce &&
                  globalThis.__terminated) {
                globalThis.__failQueueReadAfterTerminationOnce = false;
                throw new Error("queue read failed after termination");
              }
              return { Parameter: { Value: values.get(command.input.Name) || "0" } };
            }
            if (command instanceof DeleteParameterCommand) {
              values.delete(command.input.Name); return {};
            }
            if (!command.input.Overwrite && values.has(command.input.Name)) {
              const error = new Error("exists");
              error.name = "ParameterAlreadyExists";
              throw error;
            }
            if (command.input.Name === process.env.LIFECYCLE_STATE_PARAMETER &&
                globalThis.__failLifecycleWriteAfterTerminationOnce &&
                globalThis.__terminated) {
              globalThis.__failLifecycleWriteAfterTerminationOnce = false;
              throw new Error("lifecycle write failed after termination");
            }
            if (command.input.Value.includes('"state":"termination_acknowledged"') &&
                globalThis.__failTerminationAckWriteOnce) {
              globalThis.__failTerminationAckWriteOnce = false;
              throw new Error("termination acknowledgement write failed");
            }
            values.set(command.input.Name, command.input.Value);
            return {};
          }
        }
    """)
    for name in (
        "webapp_runner_aws_state.mjs",
        "webapp_runner_github_api.mjs",
        "webapp_runner_github_broker.mjs",
        "webapp_runner_registration.mjs",
        "webapp_runner_termination.mjs",
        "webapp_runner_parallel_reaper.mjs",
    ):
        (tmp_path / name).write_text((INFRA_ROOT / name).read_text())
