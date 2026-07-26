import {
  el,
  loadScopedSection,
  mergedRows,
  scopeBuckets,
  section,
  statePill,
  withProjectColumn,
} from "./universe_view_support.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { renderTestMachineDetail } from "./universe_view_test_machine.js";

const CAPABILITY_LABELS = {
  configured_unverified: "configured (unverified)",
  in_use: "in use",
};

function capabilityLabel(value) {
  const text = String(value || "");
  return CAPABILITY_LABELS[text] || text.replaceAll("_", " ");
}

function capabilityOrder(row) {
  return row.type === "test-machine" ? 0 : 1;
}

function renderCapabilityTable(body, rows, columns) {
  const documentNode = body.ownerDocument;
  if (!rows.length) {
    body.appendChild(el(
      documentNode, "p", "empty", "No capabilities in this scope.",
    ));
    return;
  }
  const table = el(documentNode, "table", "items");
  const head = el(documentNode, "tr");
  for (const column of columns) {
    head.appendChild(el(documentNode, "th", null, column.label));
  }
  table.appendChild(head);
  for (const row of rows) {
    const record = el(documentNode, "tr");
    for (const [index, column] of columns.entries()) {
      const text = String(column.value(row) ?? "");
      const cell = el(documentNode, "td", column.mono ? "mono" : null);
      if (index === 0 && row.type === "test-machine") {
        const link = el(documentNode, "a", "row-link", text);
        link.href = buildUniverseRoute(
          "capabilities", String(row.project_id), "test-machine",
        );
        cell.appendChild(link);
      } else if (column.pill) {
        const pill = statePill(
          documentNode, text, capabilityLabel(text),
        );
        if (pill) cell.appendChild(pill);
      } else {
        cell.textContent = text;
      }
      record.appendChild(cell);
    }
    table.appendChild(record);
  }
  body.appendChild(table);
}

// What Yoke can reach on a project's behalf, and how honestly it can claim
// so. The engine owns the vocabulary end to end: the capability column shows
// the STORED type string (never an invented label), kind/state arrive
// derived, and the verified stamp is whichever source the engine trusts for
// that type (the GitHub row wears its repo-binding freshness). A NULL stamp
// renders as the word "never" — configured-but-never-verified is a warning,
// not a resting state.
export function renderCapabilitiesView(context, main, scope) {
  const documentNode = context.document;
  const callout = el(documentNode, "div", "strategy-callout");
  callout.appendChild(el(
    documentNode, "span", "strategy-callout-icon", "⌘",
  ));
  const calloutCopy = el(documentNode, "span");
  calloutCopy.appendChild(el(
    documentNode, "strong", null, "Test Mac is one composite capability. ",
  ));
  calloutCopy.appendChild(el(
    documentNode,
    "span",
    null,
    "Connection, Terminal control, screenshot capture, its named host baselines, supported features, and secret references stay together because they describe one scarce machine—not six things the user should assemble by hand. A baseline is a registered operation on the capability's executor—reached and verified by code, never instructions a reader is trusted to follow.",
  ));
  callout.appendChild(calloutCopy);
  const panel = section(
    documentNode, "Capabilities", { showRaw: false },
  );
  panel.children[0].appendChild(el(
    documentNode,
    "span",
    "panel-hint",
    scope === "all" ? "across all projects" : "selected projects",
  ));
  main.replaceChildren(callout, panel);
  const buckets = scopeBuckets(scope, context.projects(), false);
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "projects.capabilities.list",
      payload: bucket === null ? {} : { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows).sort(
        (left, right) => capabilityOrder(left) - capabilityOrder(right),
      );
      panel.setCount(rows.length);
      // Each capability row carries the slug of the project declaring it.
      const columns = withProjectColumn([
        { label: "capability", value: (row) => row.type, mono: true },
        { label: "kind", value: (row) => row.kind, pill: true },
        { label: "settings", value: (row) => row.settings_summary || "—" },
        { label: "used by", value: (row) => row.used_by_summary || "—" },
        { label: "verified", value: (row) => row.verified_at || "never" },
        { label: "state", value: (row) => row.state, pill: true },
      ], scope, (row) => row.project);
      renderCapabilityTable(body, rows, columns);
    },
  );
}

export function renderCapabilityDetail(
  context, main, project, capabilityType,
) {
  if (capabilityType === "test-machine") {
    return renderTestMachineDetail(context, main, project);
  }
  main.replaceChildren(el(
    context.document,
    "p",
    "error",
    `unknown capability detail: ${capabilityType}`,
  ));
}
