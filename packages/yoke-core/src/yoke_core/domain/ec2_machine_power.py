"""EC2 implementation of the cloud Test Machine power interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from yoke_core.domain.deploy_remote import CommandRunner
from yoke_core.domain.ec2_instance_power import (
    ensure_instance_running,
    instance_public_address,
    instance_state,
    stop_instance,
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

    @property
    def stop_command(self):
        return f"yoke aws exec --project {self.project} -- ec2 stop-instances --instance-ids {self.instance_id}"

    def start(self):
        return ensure_instance_running(
            self.runner, self.instance_id, self.env, self.emit
        )

    def address(self):
        return instance_public_address(self.runner, self.instance_id, self.env)

    def stop(self):
        if instance_state(self.runner, self.instance_id, self.env) in (
            "pending",
            "running",
        ):
            stop_instance(self.runner, self.instance_id, self.env, self.emit)
