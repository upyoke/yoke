# Deployments and releases

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Deployments and releases
<!-- /yoke:breadcrumbs -->

Work items that require deployment reach Done through a deployment run of their assigned flow. The flow defines the target environment and the steps required to complete delivery, including configured CI, GitHub Actions workflows, deployment operations, QA, and approvals.

A **flow** is the reusable definition. A **run** is one execution of it. A run can deliver several work items together while tracking their individual obligations.

## Sites and environments

### Sites

A site represents a deployable part of a project, such as a web application or API service. A project can have more than one site when its software is deployed in separate units.

### Environments

An environment is a named place where that site's software runs. Its configuration can identify the URL, deployment method, health checks, and other settings needed to deliver and verify the software.

Preview, dev, staging, and Production are useful names and purposes, not a requirement to create every environment. An ephemeral target is short-lived and may be created for a branch or work item. Yoke's local hosting mode describes where the control plane runs; it is separate from an application's deployment environment.

### Environment settings

Your agent registers environments and connects the settings to the project's actual infrastructure. Onboarding configures delivery only for first dashes that deploy. [Site and environment reference](../deployments/model/flows.md)

## Deployment flows

### Item flow assignment

An item selects a delivery flow, often from its project's workflow defaults. The selection tells Yoke which delivery can complete the item. The item's workflow policy determines whether delivery is required; merely inheriting a default does not create that obligation.

A merge-only flow has no deployed target. It is suitable when the agreed completion result is a merge rather than running software in an environment.

### Stages and execution

A flow contains ordered stages. Supported runners cover automatic steps, health checks, warm-up, environment activation, supported deployment operations, GitHub Actions workflows, QA, and human approval. Your agent must configure supported runners for the real project, not just name an arbitrary stage and assume it executes.

GitHub Actions stages dispatch a configured workflow and wait for its result. CI checks establish which candidate passed the project's checks. Deployment then moves that candidate into the target environment; readiness checks establish whether the deployed service answers as required.

Database migrations follow the project's configured boot or deployment integration. They are not a generic extra migration stage in every flow. [Databases and migrations](databases.md)

<!-- yoke:visual deployment -->

### Flow versions

Used flow definitions retain their history. A changed pipeline is published as a successor definition; disabling a flow prevents new use without deleting earlier runs. The Deployments dashboard displays flows and runs separately, and agents manage definitions through Yoke's flow commands. [Flow reference](../deployments/model/flows.md)

## Deployment runs

### Starting and monitoring

A run binds a flow to a candidate and target. Your agent can start the selected item's delivery or manage a release containing several items. The Deployments and Shipping views show progress, current stages, and waits.

Starting the same delivery again may return the existing run that already holds it. A second run is not a shortcut around the first run's custody or open obligations.

### Candidates, members, and carried work

The candidate identifies the code the run will deliver. A member is an item whose delivery obligations belong to the run. Carried work is code present in the candidate without the same ownership of that item's QA and completion.

A release can include code from several projects when those source bindings are explicitly recorded. Code being present in a build does not by itself prove an item's delivery requirements are satisfied. [Run membership](../deployments/model/run-members.md)

### Stage receipts

Receipts record what a stage actually did and its outcome. They connect the pipeline's execution to evidence such as a workflow run, readiness observation, or QA result. A stage name or an intended commit is not a substitute for that execution record. [Stage receipts](../deployments/model/stage-receipts.md)

## Deployment QA and approvals

A flow can require run-level QA of the deployed candidate and item-level QA for its members. Reusable plans may be shared where their ownership, target, and selected definitions match. Each obligation keeps its own evidence and completion rules.

Where approval is configured, the dashboard presents a decision for the authorized people or roles. They can inspect the evidence and approve or reject. Approval records the decision; the run's driver resumes the pipeline. A rejection is a real outcome, not an unanswered request.

See [Quality assurance](qa.md) for methods, plans, requirements, environments, and review, and [deployment QA execution](../verification/deployment-plan-execution.md) for the detailed contract.

## Releases

### Identity and deployed versions

A release connects the candidate to what was actually deployed. Recorded source commits, deployed identity, stage results, and QA evidence let you distinguish intended code from observed running software.

### Delivery evidence and item completion

An item completes only when a run with authority for its delivery has supplied the required evidence and the item's gates are satisfied. A merge alone, carried code, or another flow's successful run may not meet that condition.

Runs can remain in settlement while required close-out work is unresolved. Read the named member or requirement that holds settlement rather than treating a successful deployment command as proof that every item is Done. [Release and completion reference](../deployments/model/releases.md)

### Notifications

Release notices and decision requests keep the responsible sessions and people informed. The durable run and member records remain the source of delivery state even if a notification arrives late. [Release notices](../deployments/model/release-notices.md)

## Run recovery

A failed stage records its reason and stops according to the flow's failure policy. Your agent should inspect the stage result, correct the cause, and use the supported retry or resume path for that run.

Cancellation and terminalization preserve the history. They do not manufacture successful QA or remove code already delivered. Interrupted drivers must reconcile the recorded run and external execution before retrying, so a lost response does not trigger duplicate deployment work. [Run recovery](../deployments/model/ended-runs.md) and [start diagnostics](../deployments/start-diagnostics.md)
