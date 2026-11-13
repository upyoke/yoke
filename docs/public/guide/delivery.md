# Deployments and releases

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Deployments and releases
<!-- /yoke:breadcrumbs -->

Work items that require deployment reach Done through a deployment run of
their assigned flow. The flow names the target environment and the stages a
delivery passes through: CI, GitHub Actions workflows, deployment steps, QA
and human approvals.

A **flow** is the reusable definition, and a **run** is one execution of it
against one commit. A run can deliver several work items together while
tracking each item's own QA and completion.

<!-- yoke:visual deployment -->

Yoke records the commit each run deployed, what every stage observed, and the
QA evidence, so you can tell intended code from running software. Follow
runs in the web dashboard, answer approvals there, and see which work reached
each environment. When a stage fails, the run records why so your agent can
fix the cause and re-drive it.

[More on Deployments](../deployments/index.md)
