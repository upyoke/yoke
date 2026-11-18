"""EC2 implementation of the cloud Test Machine power interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from yoke_core.domain.deploy_remote import CommandRunner
from yoke_core.domain.ec2_instance_power import (
    Ec2InstancePowerError,
    ensure_instance_running,
    instance_state,
    stop_instance,
    wait_for_instance_stopped,
)


@dataclass
class Ec2MachinePower:
    runner: CommandRunner
    env: dict[str, str]
    instance_id: str
    project: str
    emit: Callable[[str], None]

    @property
    def read_command(self):
        return f"yoke aws exec --project {self.project} -- ec2 describe-instances --instance-ids {self.instance_id}"

    def start(self):
        return ensure_instance_running(
            self.runner, self.instance_id, self.env, self.emit
        )

    def stop(self):
        state = instance_state(self.runner, self.instance_id, self.env)
        if state in {"pending", "running"}:
            stop_instance(self.runner, self.instance_id, self.env, self.emit)
        if state in {"pending", "running", "stopping"}:
            wait_for_instance_stopped(self.runner, self.instance_id, self.env, self.emit)
        elif state != "stopped":
            raise Ec2InstancePowerError(
                f"instance {self.instance_id} is {state}; inspect it with {self.read_command}"
            )
