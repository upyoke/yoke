import {
  buildUniverseRoute,
  serializeScope,
} from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import {
  el,
  loadScopedSection,
  mergedRows,
  renderError,
  scopeBuckets,
  section,
  statePill,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import { renderStageStrip } from "./universe_stage_strip.js";
import { runGateStatus } from "./universe_run_gates.js";
import {
  isTerminalizable,
  terminalizationDialog,
} from "./deployment_run_terminalization_dialog.js";
import { renderDeliveryFlowExplorer } from "./universe_delivery_flows.js";
import {
  createDeploymentRunsLoader,
} from "./universe_deployment_runs_loader.js";

function memberLink(documentNode, member) {
  const href = itemDrillInHref({
    projectId: member.project_id,
    projectSequence: member.project_sequence,
    publicRef: member.ref,
  });
  const link = el(
    documentNode,
    href ? "a" : "span",
    "delivery-member",
    [member.ref, member.title].filter(Boolean).join(" · "),
  );
  if (href) link.href = href;
  return link;
}

function originatingItems(documentNode, row) {
  const members = el(documentNode, "div", "delivery-origin-items");
  if ((row.member_items || []).length) {
    for (const member of row.member_items) {
      members.appendChild(memberLink(documentNode, member));
    }
  } else {
    members.appendChild(el(
      documentNode,
      "span",
      "secondary-muted",
      "environment run",
    ));
  }
  return members;
}

function runProjectLabel(projects, projectSlug) {
  const normalized = String(projectSlug || "").toLowerCase();
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value || "").toLowerCase() === normalized,
    )
  ));
  const label = project?.slug || projectSlug || project?.name || "—";
  return project?.emoji ? `${project.emoji} ${label}` : label;
}

function runTimestamp(row) {
  return row.completed_at || row.started_at || row.created_at || null;
}

function renderRunsTable(body, rows, projects, onTerminalized) {
  const documentNode = body.ownerDocument;
  if (!rows.length) {
    body.appendChild(el(documentNode, "p", "empty", "No runs in this scope."));
    return;
  }
  const wrap = el(documentNode, "div", "table-wrap");
  const table = el(documentNode, "table", "items delivery-runs-table");
  const head = el(documentNode, "tr");
  for (const label of [
    "Run", "Project", "Originating item", "Target",
    "Stages", "Status", "When",
  ]) head.appendChild(el(documentNode, "th", null, label));
  table.appendChild(head);
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "td", "mono", row.id || "—"));
    tr.appendChild(el(
      documentNode, "td", null, runProjectLabel(projects, row.project),
    ));
    const item = el(documentNode, "td");
    item.appendChild(originatingItems(documentNode, row));
    tr.appendChild(item);
    tr.appendChild(el(
      documentNode, "td", null,
      row.target_environment || row.target_tier || "—",
    ));
    const stages = el(documentNode, "td");
    stages.appendChild(renderStageStrip(documentNode, row.stages));
    tr.appendChild(stages);
    const status = el(documentNode, "td", "delivery-run-status");
    // A suspended run keeps whatever status it held when it stopped, so the
    // table reports the gate instead — the same string the run card shows.
    const shown = runGateStatus(row) || row.status;
    const pill = statePill(documentNode, shown, shown);
    if (pill) status.appendChild(pill);
    if (isTerminalizable(row)) {
      const terminalize = el(
        documentNode, "button", "delivery-run-terminalize", "Terminalize",
      );
      terminalize.type = "button";
      terminalize.addEventListener("click", () => {
        body.appendChild(terminalizationDialog(
          onTerminalized.context,
          row,
          onTerminalized.reload,
        ));
      });
      status.appendChild(terminalize);
    }
    tr.appendChild(status);
    const when = el(documentNode, "td");
    when.appendChild(relativeTime(documentNode, runTimestamp(row)));
    tr.appendChild(when);
    table.appendChild(tr);
  }
  wrap.appendChild(table);
  body.appendChild(wrap);
}

export function renderDeliveryRunsView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Runs");
  panel.classList.add("delivery-facet-panel");
  const controls = el(documentNode, "div", "item-filters delivery-run-filters");
  const query = el(documentNode, "input", "item-filter-control");
  query.type = "search";
  query.placeholder = "Run ID or originating item";
  controls.appendChild(query);
  const selectSpecs = [
    ["project", "All projects"],
    ["status", "All statuses"],
    ["environment", "All environments"],
    ["flow", "All flows"],
  ];
  const selects = new Map();
  for (const [key, label] of selectSpecs) {
    const select = el(documentNode, "select", "item-filter-control");
    selects.set(key, { select, label, signature: null });
    controls.appendChild(select);
  }
  main.replaceChildren(controls, panel);

  const loader = createDeploymentRunsLoader({
    context,
    scope,
    onChange: renderState,
  });
  query.addEventListener("input", () => loader.setQuery(query.value));
  for (const [key, { select }] of selects) {
    select.addEventListener("change", () => loader.setFilter(key, select.value));
  }

  function updateControls(state) {
    const choices = {
      project: state.filters.projects || [],
      status: (state.filters.statuses || []).map((id) => ({ id, label: id })),
      environment: (state.filters.environments || []).map(
        (id) => ({ id, label: id }),
      ),
      flow: state.filters.flows || [],
    };
    for (const [key, entry] of selects) {
      const signature = JSON.stringify(choices[key]);
      if (signature !== entry.signature) {
        entry.signature = signature;
        const empty = el(documentNode, "option", null, entry.label);
        empty.value = "";
        const options = [empty];
        for (const choice of choices[key]) {
          const option = el(documentNode, "option", null, choice.label);
          option.value = String(choice.id);
          options.push(option);
        }
        entry.select.replaceChildren(...options);
      }
      entry.select.value = state.criteria[key];
    }
  }

  function renderState(state) {
    if (!context.isMounted()) return;
    updateControls(state);
    if (state.failure && !state.rows.length) {
      panel.renderEnvelope(state.failure, (body) => renderError(body, state.failure));
      return;
    }
    panel.setCount(state.unfinishedCount + state.completedMatchCount);
    panel.renderEnvelopes([], (body) => {
      if (state.loading && !state.rows.length) {
        body.appendChild(el(documentNode, "p", "empty", "loading…"));
        return;
      }
      body.appendChild(el(
        documentNode,
        "p",
        "item-roster-note delivery-run-counts",
        `${state.unfinishedCount} unfinished · `
          + `${state.completedLoadedCount} of ${state.completedMatchCount} completed loaded`,
      ));
      renderRunsTable(body, state.rows, context.projects(), {
        context,
        reload: loader.start,
      });
      const waiting = state.rows.filter(
        (row) => (row.gates || []).some((gate) => gate.can_act),
      ).length;
      if (waiting) {
        const inbox = el(
          documentNode,
          "a",
          "delivery-waiting-link",
          `${waiting} run${waiting === 1 ? "" : "s"} waiting on you →`,
        );
        inbox.href = buildUniverseRoute("inbox", serializeScope(scope));
        body.appendChild(inbox);
      }
      if (!state.hasMore && !state.failure) return;
      const more = el(documentNode, "div", "item-roster-more");
      if (state.failure) renderError(more, state.failure);
      if (state.hasMore) {
        const button = el(
          documentNode,
          "button",
          "item-button deployment-runs-more",
          state.loading ? "Loading…" : "Load more",
        );
        button.type = "button";
        button.disabled = state.loading;
        button.addEventListener("click", () => { loader.loadMore(); });
        more.appendChild(button);
      }
      body.appendChild(more);
    });
  }

  loader.start();
}

export function renderDeliveryFlowsView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Flows");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context,
    panel,
    buckets.map((bucket) => ({
      functionId: "workflows.definition.get",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.flows);
      renderDeliveryFlowExplorer(body, panel, rows, {
        client: context.client,
        reload: () => renderDeliveryFlowsView(context, main, scope),
      });
    },
  );
}
