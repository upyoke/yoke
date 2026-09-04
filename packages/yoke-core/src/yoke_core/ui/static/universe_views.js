// Read-only function-backed workbench views; the app shell owns routing and
// universe_view_support.js owns presentation primitives.

import {
  renderArchitectureView,
} from "./universe_views_architecture.js";
import {
  renderCapabilitiesView,
  renderCapabilityDetail,
} from "./universe_views_capabilities.js";
import {
  renderDeliveryFlowsView,
  renderDeliveryRunsView,
} from "./universe_views_delivery.js";
import {
  renderDeliveryDatabasesView,
  renderDeliveryEnvironmentsView,
} from "./universe_views_delivery_inventory.js";
import { renderDoctorView } from "./universe_views_doctor.js";
import { renderEventsView } from "./universe_views_events.js";
import { renderGithubView } from "./universe_views_github.js";
import { renderInboxView } from "./universe_views_inbox.js";
import {
  renderItemDetailView,
  renderItemsView,
} from "./universe_views_items.js";
import { renderOrganizationView } from "./universe_views_organization.js";
import {
  renderOuroborosEntryDetailView,
  renderOuroborosView,
} from "./universe_views_ouroboros.js";
import { renderOverviewView } from "./universe_views_overview.js";
import { renderPacksView } from "./universe_views_packs.js";
import {
  renderProjectsView,
  renderProjectView,
} from "./universe_views_projects.js";
import {
  renderQaActivity,
  renderQaMethodDetail,
  renderQaMethods,
  renderQaPlanDetail,
  renderQaPlans,
} from "./universe_views_qa.js";
import { renderSessionsView } from "./universe_views_sessions.js";
import { renderSessionMessagesView } from "./universe_session_messages.js";
import { renderRegisteredSessionDetail } from "./universe_session_detail.js";
import { renderMachinesView } from "./universe_views_machines.js";
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
  strategy: renderStrategyDocDetailView,
  capabilities: renderCapabilityDetail,
  ouroboros: renderOuroborosEntryDetailView,
  // Projects and Project settings were a list and a form for one thing:
  // opening a project row IS opening its settings.
  projects: renderProjectView,
  sessions: fromDrillInProject(renderRegisteredSessionDetail),
  "qa-methods": fromDrillInProject(renderQaMethodDetail),
  "qa-plans": fromDrillInProject(renderQaPlanDetail),
};

// A destination is live exactly when it has a renderer here.
// Every facet that earned a name is a destination. A tab was one facet of a
// view's single concept; a facet an operator navigates to is a destination,
// and calling it a tab only hid it one level down.
export const VIEW_RENDERERS = {
  overview: renderOverviewView,
  sessions: renderSessionsView,
  inbox: renderInboxView,

  organization: renderOrganizationView,
  workflows: renderWorkflowsView,
  projects: renderProjectsView,
  github: renderGithubView,

  strategy: renderStrategyView,
  items: renderItemsView,
  deployments: renderDeliveryRunsView,
  environments: renderDeliveryEnvironmentsView,
  flows: renderDeliveryFlowsView,
  databases: renderDeliveryDatabasesView,
  "qa-methods": renderQaMethods,
  "qa-plans": renderQaPlans,
  "qa-activity": renderQaActivity,
  capabilities: renderCapabilitiesView,
  packs: renderPacksView,
  architecture: renderArchitectureView,
  messages: renderSessionMessagesView,
  events: renderEventsView,
  doctor: renderDoctorView,
  ouroboros: renderOuroborosView,
  machines: renderMachinesView,
};
