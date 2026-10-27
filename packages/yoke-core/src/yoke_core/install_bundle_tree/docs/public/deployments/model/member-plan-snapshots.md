# Frozen member plans

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Deployments](../index.md) > Frozen member plans
<!-- /yoke:breadcrumbs -->

When a plan is attached at several workflow boundaries, the frozen snapshot
uses the live attachment matching its admitted requirements' QA phase and
transition. When none matches, it retains the first live attachment.

An incomplete frozen plan blocks QA, but does not block removing that member
at independent item QA with `yoke deployment-runs remove-item RUN PREFIX-N
--reason R`. The usual driver, stage, shared-gate and closed-member guards
still apply. Removal preserves QA history and protects remaining shared
owners; repairing historical acceptance still needs original admission evidence.

## Related

- [Run members and QA](run-members.md)
