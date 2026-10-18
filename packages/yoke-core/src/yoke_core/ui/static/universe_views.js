import { deferredRenderer } from "./universe_view_loader.js";
// Read-only function-backed workbench views; the app shell owns routing and
// universe_view_support.js owns presentation primitives.

const renderArchitectureView = deferredRenderer(() => import("./universe_views_architecture.js"), "renderArchitectureView");
const renderCapabilitiesView = deferredRenderer(() => import("./universe_views_capabilities.js"), "renderCapabilitiesView");
const renderCapabilityDetail = deferredRenderer(() => import("./universe_views_capabilities.js"), "renderCapabilityDetail");
const renderDeploymentsView = deferredRenderer(() => import("./universe_views_delivery.js"), "renderDeploymentsView");
const renderFrontierView = deferredRenderer(() => import("./universe_views_frontier.js"), "renderFrontierView");
const renderShippingView = deferredRenderer(() => import("./universe_views_shipping.js"), "renderShippingView");
const renderDeliveryDatabasesView = deferredRenderer(() => import("./universe_views_delivery_inventory.js"), "renderDeliveryDatabasesView");
const renderDeliveryEnvironmentsView = deferredRenderer(() => import("./universe_views_delivery_inventory.js"), "renderDeliveryEnvironmentsView");
const renderDoctorView = deferredRenderer(() => import("./universe_views_doctor.js"), "renderDoctorView");
const renderEventsView = deferredRenderer(() => import("./universe_views_events.js"), "renderEventsView");
const renderPerformanceView = deferredRenderer(() => import("./universe_views_performance.js"), "renderPerformanceView");
const renderGithubView = deferredRenderer(() => import("./universe_views_github.js"), "renderGithubView");
const renderInboxView = deferredRenderer(() => import("./universe_views_inbox.js"), "renderInboxView");
const renderRunDetailView = deferredRenderer(() => import("./universe_views_run_detail.js"), "renderRunDetailView");
const renderItemDetailView = deferredRenderer(() => import("./universe_views_items.js"), "renderItemDetailView");
const renderItemsView = deferredRenderer(() => import("./universe_views_items.js"), "renderItemsView");
const renderOrganizationView = deferredRenderer(() => import("./universe_views_organization.js"), "renderOrganizationView");
const renderLevelsView = deferredRenderer(() => import("./universe_views_levels.js"), "renderLevelsView");
const renderActorsView = deferredRenderer(() => import("./universe_views_actors.js"), "renderActorsView");
const renderProfileView = deferredRenderer(() => import("./universe_views_profile.js"), "renderProfileView");
const renderOuroborosEntryDetailView = deferredRenderer(() => import("./universe_views_ouroboros.js"), "renderOuroborosEntryDetailView");
const renderOuroborosView = deferredRenderer(() => import("./universe_views_ouroboros.js"), "renderOuroborosView");
const renderPacksView = deferredRenderer(() => import("./universe_views_packs.js"), "renderPacksView");
const renderProjectsView = deferredRenderer(() => import("./universe_views_projects.js"), "renderProjectsView");
const renderProjectView = deferredRenderer(() => import("./universe_views_projects.js"), "renderProjectView");
const renderQaActivity = deferredRenderer(() => import("./universe_views_qa.js"), "renderQaActivity");
const renderQaCaseDetail = deferredRenderer(() => import("./universe_views_qa.js"), "renderQaCaseDetail");
const renderQaMethodDetail = deferredRenderer(() => import("./universe_views_qa.js"), "renderQaMethodDetail");
const renderQaMethods = deferredRenderer(() => import("./universe_views_qa.js"), "renderQaMethods");
const renderQaPlanDetail = deferredRenderer(() => import("./universe_views_qa.js"), "renderQaPlanDetail");
const renderQaPlans = deferredRenderer(() => import("./universe_views_qa.js"), "renderQaPlans");
const renderSessionsView = deferredRenderer(() => import("./universe_views_sessions.js"), "renderSessionsView");
const renderSessionMessagesView = deferredRenderer(() => import("./universe_session_messages.js"), "renderSessionMessagesView");
const renderRegisteredSessionDetail = deferredRenderer(() => import("./universe_session_detail.js"), "renderRegisteredSessionDetail");
const renderMachineApproval = deferredRenderer(() => import("./machine_approval.js"), "renderMachineApproval");
const renderMachinesView = deferredRenderer(() => import("./universe_views_machines.js"), "renderMachinesView");
const renderSessionLaunchesView = deferredRenderer(() => import("./universe_session_launches.js"), "renderSessionLaunchesView");
const renderMachineDetail = deferredRenderer(() => import("./universe_machine_detail.js"), "renderMachineDetail");
const renderStrategyDocDetailView = deferredRenderer(() => import("./universe_views_strategy.js"), "renderStrategyDocDetailView");
const renderStrategyView = deferredRenderer(() => import("./universe_views_strategy.js"), "renderStrategyView");
const renderWorkflowsView = deferredRenderer(() => import("./universe_views_workflows.js"), "renderWorkflowsView");

export { section } from "./universe_view_support.js";

// A view drill-in is handed ONE project id; the facets that used to be tabs
// were handed the whole scope, because a facet sat under a scoped view. Their
// renderers still read a scope, so the id becomes the one-project scope it
// describes rather than every one of them changing shape.
const fromDrillInProject = (render) => (
  (context, main, project, detail, navigation) => render(
    context, main, project === null ? null : [String(project)], detail, navigation,
  )
);

// Drill-ins remain children of the view whose row opened them.
export const DETAIL_RENDERERS = {
  items: renderItemDetailView,
  // Opening a run from Shipping IS opening the run: a sub-screen of the
  // page that listed it, reached through that page's breadcrumb. The
  // Deployments drill-in below reaches the same renderer from the
  // diagnostics side, where a run is read beside the flow that defines it.
  shipping: fromDrillInProject(renderRunDetailView),
  strategy: renderStrategyDocDetailView,
  capabilities: renderCapabilityDetail,
  ouroboros: renderOuroborosEntryDetailView,
  // Projects and Project settings were a list and a form for one thing:
  // opening a project row IS opening its settings.
  projects: renderProjectView,
  sessions: fromDrillInProject(renderRegisteredSessionDetail),
  machines: renderMachineDetail,
  "qa-methods": fromDrillInProject(renderQaMethodDetail),
  "qa-plans": fromDrillInProject(renderQaPlanDetail),
  // Opening an Activity row IS opening that case: its own record, the
  // stage execution that judged it, and the evidence it captured. It reads
  // one project's row rather than a scope, so it takes the drill-in project
  // as given.
  "qa-activity": renderQaCaseDetail,
  // What a Deployments drill-in means depends on the tab it hangs off.
  // Opening a run row IS opening the run: the page it lands on reads the same
  // run row the table did, plus the QA activity recorded against it. A flow
  // link instead opens the Flows tab on that definition, keeping the tab
  // strip and the catalog beside it rather than replacing the page.
  deployments: (context, main, project, detail, navigation) => (
    navigation?.tab === "flows"
      ? renderDeploymentsView(
        context, main, project === null ? null : [String(project)],
        { tab: "flows", detail },
      )
      : fromDrillInProject(renderRunDetailView)(
        context, main, project, detail, navigation,
      )
  ),
};

// A destination is live exactly when it has a renderer here.
// Most facets that earned a name are destinations: a facet an operator
// navigates to deserves its own sidebar entry, and calling it a tab only hid
// it one level down. A destination keeps tabs only where its facets are two
// readings of one subject — Deployments, whose Flows define what its Runs
// execute — and then the renderer below reads `chrome.tab` to pick one.
export const VIEW_RENDERERS = {
  strategy: renderStrategyView,
  frontier: renderFrontierView,
  shipping: renderShippingView,
  machines: renderMachinesView,
  "machine-approval": renderMachineApproval,
  sessions: renderSessionsView,
  inbox: renderInboxView,
  profile: renderProfileView,

  organization: renderOrganizationView,
  levels: renderLevelsView,
  actors: renderActorsView,
  workflows: renderWorkflowsView,
  projects: renderProjectsView,
  github: renderGithubView,

  items: renderItemsView,
  deployments: renderDeploymentsView,
  environments: renderDeliveryEnvironmentsView,
  databases: renderDeliveryDatabasesView,
  "qa-methods": renderQaMethods,
  "qa-plans": renderQaPlans,
  "qa-activity": renderQaActivity,
  capabilities: renderCapabilitiesView,
  packs: renderPacksView,
  architecture: renderArchitectureView,
  messages: renderSessionMessagesView,
  launches: renderSessionLaunchesView,
  events: renderEventsView,
  performance: renderPerformanceView,
  doctor: renderDoctorView,
  ouroboros: renderOuroborosView,
};
