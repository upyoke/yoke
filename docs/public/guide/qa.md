# Quality assurance

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Quality assurance
<!-- /yoke:breadcrumbs -->

Yoke connects work to the checks and evidence required to call it done. Agents define QA requirements, run checks through configured methods, and record their results. You can follow the evidence and make decisions where human approval is required.

A check can happen before merge, after merge, or after deployment. Its subject, target, and required point in the workflow determine what it proves and when it must pass.

## Types of QA

### Item QA

Item QA proves the requirements of a particular work item. Some requirements gate implementation review; others must be answered against deployed software or need human acceptance. Item QA is not synonymous with pre-merge testing.

An item's source requirement can be admitted into a deployment run so its result is tied to the deployed candidate, environment, and member. Completing an unrelated test run does not satisfy that obligation.

### Deployment run QA

Deployment run QA checks a deployed candidate at a QA stage of a flow. The requirement belongs to the run and stage, with member identity when the stage scopes checks to individual items.

The candidate identifies the code being delivered. Members identify the items whose delivery the run owns. Where a release must prove a producer and consumer together, consumer proof verifies that exact configured combination. [Deployment QA](../verification/deployment-plan-execution.md) and [consumer proof](../verification/consumer-proof.md)

### Shared item QA

Several items can attach the same reusable plan and share an eligible execution. Sharing is explicit: the execution must match the frozen plan, target, and owning members. Similar case names or an earlier green result do not create shared credit automatically. [QA continuity](../verification/deployment-qa-continuity.md)

### Standalone QA

A standalone plan execution checks a project without attaching the work to an item or deployment run. It still records the selected plan, cases, execution, and evidence. It does not silently satisfy an unrelated item gate. [Standalone plans](../verification/standalone-plans.md)

## Methods, cases, and plans

### QA methods

A method defines how a check executes and produces a verdict. Built-in methods include commands, CI-backed commands, browser checks, and agent exploration. Methods can require capabilities on the project or the machine running them.

Choose a deterministic method when the expected behavior can be stated precisely. Use agent judgment when checking usability, investigating a complex situation, or assessing behavior that needs interpretation. The method's declared evidence and review requirements still apply.

### QA cases

A case describes an individual check: what to do, the expected outcome, the method and its configuration, and the target or starting state it needs. A useful case makes the intended proof understandable before someone reads its logs.

### QA plans

A plan groups cases into a reusable sequence. Plans can be copied and adapted for another feature or environment. Ordering matters when a case intentionally inherits the state left by an earlier case.

### Registered commands and project defaults

Registered commands bind an existing project test command to a reusable QA plan. Common scopes include quick, full, end-to-end, and smoke checks. Source-level checks and deployed checks use different target configuration.

Project defaults attach the appropriate plans to work automatically. A GitHub Actions test workflow can route supported checks to CI; otherwise command checks can run locally. If the project has no runnable tests, record that posture explicitly rather than presenting an empty requirement list as passing evidence. [Command binding and defaults](../verification/index.md)

## Requirements and gates

### Attachments and materialized requirements

An attachment selects a case or plan for an item, workflow transition, or deployment scope. Materialization creates the concrete requirements that must be answered for that work. The reusable definition and the resulting obligation are related, but they are not the same record.

### Phases and blocking modes

Verification requirements gate implementation review. Post-deploy requirements need evidence for the applicable deployed target. Manual acceptance requires the configured human sign-off. A blocking requirement prevents the relevant transition while unsatisfied; a non-blocking requirement records evidence without holding that gate.

### Success policies

Applicable blocking requirements must all be satisfied. Yoke selects the current actual attempt; an older pass does not hide a newer failure or unfinished attempt. Method-specific measurements can decide whether one attempt passes, but repeated attempts are not votes. [Success policy](../verification/success-policy.md)

### Waivers, supersession, and retraction

A waiver explicitly discharges an obligation with an accountable reason. Supersession replaces a requirement while preserving its correction history. Retraction removes an obligation through an authorized lifecycle action. These are distinct from passing a check and remain visible in the record. [Requirement state](../verification/requirement-state.md)

## Environments and test machines

The target environment is the software being checked. The execution target is where the checking process runs. A browser may run on a test machine while exercising an application deployed elsewhere.

Targets can be local, a named preview environment such as dev or staging, an ephemeral environment, or Production. Projects configure the environments they actually use; no project needs every kind.

Test Machines register the capabilities and runtime available to a check. Leases prevent two executions from using the same exclusive resource at once. Starting-state requirements and cleanup determine whether a case uses the machine as it is, restores a baseline, or inherits state from an earlier case. [Test Machine setup](../verification/test-machine-desktop.md)

## Browser and exploratory QA

### Browser scenarios and identities

A browser scenario defines actions and assertions. A browser identity supplies the intended signed-in persona and permitted sites. Identity configuration must match the target; a missing identity is not permission to borrow another user's session.

Browser evidence can include screenshots, action results, traces, and observations of the software under test. See [scenarios](../verification/browser-scenarios.md), [identities](../verification/browser-identities.md), and [evidence](../verification/browser-evidence.md).

### Exploratory missions and real-harness QA

An exploratory mission gives an agent a goal and scope for investigation. A walker captures observations, and the responsible reviewer judges the resulting evidence. Real-harness QA exercises the actual coding-agent environment when that environment is part of the behavior being verified. [Exploration](../verification/exploration.md) and [real-harness QA](../verification/real-harness.md)

<!-- yoke:visual qa -->

## Execution and results

A QA run records one attempt at a requirement. A plan execution coordinates its case runs, order, state, and resources. Artifacts hold the evidence, such as screenshots, logs, and traces.

A verdict can pass, fail, remain undetermined, or report an execution error. Where independent or human review is required, a successful capture alone is not a final pass. Review judges the actual captured attempt against the expected outcome.

Retries preserve previous attempts. Recovery should address the named failure, restore any required target or machine state, and produce fresh evidence where needed. The QA Activity dashboard shows outcomes; plans expose failed cases and cases awaiting review. [QA platform](../verification/platform.md)

See [Workflows and work items](work.md) for item gates and [Deployments and releases](delivery.md) for deployment stages and approvals.
