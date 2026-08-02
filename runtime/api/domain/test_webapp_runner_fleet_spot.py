"""Runner fleet purchase-option coverage.

Sibling of ``test_webapp_runner_fleet_stack.py``; kept separate so neither
file approaches the authored-file line limit.
"""

from __future__ import annotations

from runtime.api.domain.webapp_runner_fleet_test_support import _runner_stack


def test_asg_buys_spare_capacity_and_replaces_reclaimed_hosts(monkeypatch):
    """Runners are disposable, so the fleet defaults to spare (spot) capacity.

    An ASG can only hold spot through a mixed-instances policy, so the policy
    carries the launch template instead of the plain ``launch_template`` arg.
    """
    recorder, _stack = _runner_stack(monkeypatch)
    asg = recorder.single("runnerFleetAsg")

    assert "launch_template" not in asg.kwargs
    policy = asg.kwargs["mixed_instances_policy"]
    template_spec = policy.kwargs["launch_template"].kwargs[
        "launch_template_specification"
    ]
    assert template_spec.kwargs["launch_template_id"].value == (
        "runnerFleetLaunchTemplate.id"
    )
    assert template_spec.kwargs["version"] == "$Latest"

    distribution = policy.kwargs["instances_distribution"]
    assert distribution.kwargs["on_demand_base_capacity"] == 0
    assert distribution.kwargs["on_demand_percentage_above_base_capacity"] == 0
    assert distribution.kwargs["spot_allocation_strategy"] == (
        "price-capacity-optimized"
    )
    assert asg.kwargs["capacity_rebalance"] is True


def test_asg_can_hold_an_on_demand_floor(monkeypatch):
    """Raising the on-demand base keeps runners a spot shortage cannot take."""
    recorder, _stack = _runner_stack(
        monkeypatch,
        spot_on_demand_base_capacity=1,
        spot_on_demand_percentage_above_base=50,
    )
    distribution = recorder.single("runnerFleetAsg").kwargs[
        "mixed_instances_policy"
    ].kwargs["instances_distribution"]

    assert distribution.kwargs["on_demand_base_capacity"] == 1
    assert distribution.kwargs["on_demand_percentage_above_base_capacity"] == 50
