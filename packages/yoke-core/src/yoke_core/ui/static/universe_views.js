// Read-only function-backed workbench views; the app shell owns routing and
// universe_view_support.js owns presentation primitives.

import {
  renderArchitectureView,
} from "./universe_views_architecture.js";
import {
  renderCapabilitiesView,
  renderCapabilityDetail,
} from "./universe_views_capabilities.js";
import { renderDeploymentsView } from "./universe_views_delivery.js";
import { renderFrontierView } from "./universe_views_frontier.js";
import { renderShippingView } from "./universe_views_shipping.js";
import {
  renderDeliveryDatabasesView,
  renderDeliveryEnvironmentsView,
} from "./universe_views_delivery_inventory.js";
import { renderDoctorView } from "./universe_views_doctor.js";
import { renderEventsView } from "./universe_views_events.js";
import { renderGithubView } from "./universe_views_github.js";
import { renderInboxView } from "./universe_views_inbox.js";
import { renderRunDetailView } from "./universe_views_run_detail.js";
import {
  renderItemDetailView,
  renderItemsView,
} from "./universe_views_items.js";
import { renderOrganizationView } from "./universe_views_organization.js";
import { renderActorsView } from "./universe_views_actors.js";
import { renderProfileView } from "./universe_views_profile.js";
import {
  renderOuroborosEntryDetailView,
  renderOuroborosView,
} from "./universe_views_ouroboros.js";
import { renderPacksView } from "./universe_views_packs.js";
import {
  renderProjectsView,
  renderProjectView,
} from "./universe_views_projects.js";
import {
  renderQaActivity,
  renderQaCaseDetail,
  renderQaMethodDetail,
  renderQaMethods,
  renderQaPlanDetail,
  renderQaPlans,
} from "./universe_views_qa.js";
import { renderSessionsView } from "./universe_views_sessions.js";
import { renderSessionMessagesView } from "./universe_session_messages.js";
import { renderRegisteredSessionDetail } from "./universe_session_detail.js";
import { renderMachinesView } from "./universe_views_machines.js";
import { renderSessionLaunchesView } from "./universe_session_launches.js";
import { renderMachineDetail } from "./universe_machine_detail.js";
import {
  renderStrategyDocDetailView,
  renderStrategyView,
} from "./universe_views_strategy.js";
import { renderWorkflowsView } from "./universe_views_workflows.js";

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
  sessions: renderSessionsView,
  inbox: renderInboxView,
  profile: renderProfileView,

  organization: renderOrganizationView,
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
  doctor: renderDoctorView,
  ouroboros: renderOuroborosView,
};
