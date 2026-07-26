// Read-only function-backed workbench views; the app shell owns routing and
// universe_view_support.js owns presentation primitives.

import {
  renderCapabilitiesView,
  renderCapabilityDetail,
} from "./universe_views_capabilities.js";
import {
  renderDeliveryFlowsView,
  renderDeliveryRunsView,
} from "./universe_views_delivery.js";
import { renderDoctorView } from "./universe_views_doctor.js";
import { renderEventsView } from "./universe_views_events.js";
import { renderFrontierView } from "./universe_views_frontier.js";
import { renderGithubView } from "./universe_views_github.js";
import { renderInboxView } from "./universe_views_inbox.js";
import {
  renderItemDetailView,
  renderItemsView,
} from "./universe_views_items.js";
import { renderOrganizationView } from "./universe_views_organization.js";
import { renderOuroborosView } from "./universe_views_ouroboros.js";
import { renderOverviewView } from "./universe_views_overview.js";
import { renderPacksView } from "./universe_views_packs.js";
import { renderProjectsView } from "./universe_views_projects.js";
import {
  renderQaActivity,
  renderQaMethods,
  renderQaPlans,
} from "./universe_views_qa.js";
import { renderSessionsView } from "./universe_views_sessions.js";
import {
  renderStrategyDocDetailView,
  renderStrategyView,
} from "./universe_views_strategy.js";
import { renderWorkflowsView } from "./universe_views_workflows.js";

export { section } from "./universe_view_support.js";

// Drill-ins remain children of the view whose row opened them.
export const DETAIL_RENDERERS = {
  items: renderItemDetailView,
  strategy: renderStrategyDocDetailView,
  capabilities: renderCapabilityDetail,
};

// Tab renderers, keyed view id → tab id. A tab is live exactly when it has a
// renderer here; a declared tab without one renders the honest stub. A view
// appears here only when its NAV entry declares tabs — the same second route
// segment cannot also be a drill-in.
export const TAB_RENDERERS = {
  delivery: { runs: renderDeliveryRunsView, flows: renderDeliveryFlowsView },
  qa: {
    methods: renderQaMethods,
    plans: renderQaPlans,
    activity: renderQaActivity,
  },
};

// A destination is live exactly when it has a renderer here.
export const VIEW_RENDERERS = {
  overview: renderOverviewView,
  inbox: renderInboxView,
  frontier: renderFrontierView,
  items: renderItemsView,
  strategy: renderStrategyView,
  sessions: renderSessionsView,
  capabilities: renderCapabilitiesView,
  events: renderEventsView,
  doctor: renderDoctorView,
  ouroboros: renderOuroborosView,
  projects: renderProjectsView,
  packs: renderPacksView,
  workflows: renderWorkflowsView,
  github: renderGithubView,
  organization: renderOrganizationView,
};
