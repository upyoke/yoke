import {
  buildUniverseRoute,
  serializeScope,
} from "./universe_navigation.js";
import {
  el,
  loadScopedSection,
  mergedRows,
  renderError,
  scopeBuckets,
  section,
} from "./universe_view_support.js";
import { renderDeliveryFlowExplorer } from "./universe_delivery_flows.js";
import {
  createDeploymentRunsLoader,
} from "./universe_deployment_runs_loader.js";
import { renderRunsTable } from "./universe_delivery_runs_table.js";
import { EMPTY_RUN_FACTS, loadRunFacts } from "./universe_run_evidence.js";

export function renderDeliveryRunsView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Runs");
  panel.classList.add("delivery-facet-panel");
  const controls = el(documentNode, "div", "item-filters delivery-run-filters");
  const query = el(documentNode, "input", "item-filter-control");
  query.type = "search";
  query.placeholder = "Run ID or carried item";
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

  // The QA checks and flow names beside each run are read once for the
  // scope and joined into every page the loader serves.
  let facts = EMPTY_RUN_FACTS;
  let lastState = null;
  const projectIds = scopeBuckets(scope, context.projects(), true);
  loadRunFacts(context, projectIds).then((loaded) => {
    facts = loaded;
    if (lastState) renderState(lastState);
  });

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
    lastState = state;
    updateControls(state);
    if (state.failure && !state.rows.length) {
      panel.renderEnvelope(state.failure, (body) => renderError(body, state.failure));
      return;
    }
    // The flow filter already labels every flow the page knows; the table
    // reads its titles from there and from the definitions read beside it.
    const flowLabels = new Map(facts.flowNames);
    for (const flow of state.filters.flows || []) {
      if (flow?.id && flow.label) flowLabels.set(String(flow.id), String(flow.label));
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
      renderRunsTable(context, body, state.rows, {
        facts, flowLabels, scope, reload: loader.start,
      });
      if (facts.failed) {
        body.appendChild(el(
          documentNode, "p", "item-roster-note delivery-run-counts", facts.failed,
        ));
      }
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
