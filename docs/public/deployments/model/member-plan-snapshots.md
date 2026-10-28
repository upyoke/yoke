# Frozen member plans

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Deployments](../index.md) > Frozen member plans
<!-- /yoke:breadcrumbs -->

Admission freezes a member's item cases, never its post-deploy plans. Each
attached post-deploy plan runs as a plan group at item QA, pinned at the run's
first group of that plan ([plan groups](../../verification/deployment-plan-execution.md#plan-groups)).

An incomplete frozen item case blocks QA, but does not block removing that
member at independent item QA with `yoke deployment-runs remove-item RUN
PREFIX-N --reason R`. The usual driver, stage and closed-member guards still
apply. Removal preserves QA history and keeps a plan group open while another
member attaches its plan; repairing historical acceptance still needs original
admission evidence.

## Related

- [Run members and QA](run-members.md)
