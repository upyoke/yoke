import {
  el,
  loadScopedSection,
  mergedRows,
  scopeBuckets,
  section,
  statePill,
} from "./universe_view_support.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { renderTestMachineDetail } from "./universe_view_test_machine.js";
import { relativeTime } from "./universe_time.js";

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

function wireCapabilityRouteRow(documentNode, record, href) {
  const navigate = () => {
    documentNode.defaultView.location.hash = href;
  };
  record.classList.add("capability-route-row");
  record.setAttribute("role", "link");
  record.setAttribute("tabindex", "0");
  record.setAttribute("aria-label", "Open Test Mac capability");
  record.addEventListener("click", (event) => {
    if (event.defaultPrevented) return;
    if (event.button !== undefined && event.button !== 0) return;
    if (event.target?.closest?.("a")) return;
    navigate();
  });
  record.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    navigate();
  });
}

function renderCapabilityTable(body, rows, columns) {
  const documentNode = body.ownerDocument;
  const table = el(documentNode, "table", "items");
  const head = el(documentNode, "tr");
  for (const column of columns) {
    head.appendChild(el(documentNode, "th", null, column.label));
  }
  table.appendChild(head);
  if (!rows.length) {
    const emptyRow = el(documentNode, "tr");
    const emptyCell = el(
      documentNode, "td", "empty", "No capabilities in this scope.",
    );
    emptyCell.colSpan = columns.length;
    emptyCell.setAttribute("colspan", String(columns.length));
    emptyRow.appendChild(emptyCell);
    table.appendChild(emptyRow);
    const emptyWrap = el(documentNode, "div", "table-wrap");
    emptyWrap.appendChild(table);
    body.appendChild(emptyWrap);
    return;
  }
  for (const row of rows) {
    const record = el(documentNode, "tr");
    const detailHref = row.type === "test-machine"
      ? buildUniverseRoute(
        "capabilities", String(row.project_id), "test-machine",
      )
      : null;
    if (detailHref) {
      wireCapabilityRouteRow(documentNode, record, detailHref);
    }
    for (const [index, column] of columns.entries()) {
      const value = column.value(row);
      const isNode = Boolean(
        value && typeof value === "object" &&
        (value.nodeType || value.tagName),
      );
      const text = isNode ? value.textContent : String(value ?? "");
      const cell = el(documentNode, "td", column.mono ? "mono" : null);
      if (index === 0 && detailHref) {
        const link = el(documentNode, "a", "row-link", text);
        link.href = detailHref;
        cell.appendChild(link);
      } else if (column.pill) {
        const pill = statePill(
          documentNode,
          text,
          column.display ? column.display(row) : capabilityLabel(text),
        );
        if (pill) cell.appendChild(pill);
      } else if (isNode) {
        cell.appendChild(value);
      } else {
        cell.textContent = text;
      }
      record.appendChild(cell);
    }
    table.appendChild(record);
  }
  const wrap = el(documentNode, "div", "table-wrap");
  wrap.appendChild(table);
  body.appendChild(wrap);
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
  const projects = context.projects();
  const projectByKey = new Map();
  for (const project of projects) {
    for (const key of [project.id, project.slug, project.name]) {
      if (key !== null && key !== undefined && String(key)) {
        projectByKey.set(String(key), project);
      }
    }
  }
  const projectLabel = (row) => {
    const project = projectByKey.get(String(row.project_id ?? "")) ||
      projectByKey.get(String(row.project ?? ""));
    const label = row.project || project?.slug || project?.name || "—";
    return project?.emoji ? `${project.emoji} ${label}` : label;
  };
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
    "Connection, Terminal control, screenshot capture, its named host baselines, supported features, and secret references stay together because they describe one scarce machine—not six things the user should assemble by hand. A baseline is a registered operation on the capability's executor — reached and verified by code, never instructions a reader is trusted to follow.",
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
  const buckets = scopeBuckets(scope, projects, false);
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
      const columns = [
        {
          label: "capability",
          value: (row) => row.display_type || row.type,
          mono: true,
        },
        { label: "project", value: projectLabel },
        { label: "kind", value: (row) => row.kind, pill: true },
        { label: "settings", value: (row) => row.settings_summary || "—" },
        { label: "used by", value: (row) => row.used_by_summary || "—" },
        {
          label: "verified",
          value: (row) => row.verified_at
            ? relativeTime(documentNode, row.verified_at)
            : "never",
        },
        {
          label: "state",
          value: (row) => row.state,
          display: (row) => {
            const label = capabilityLabel(row.state);
            return row.state === "in_use" && row.active_item_ref
              ? `${label} · ${row.active_item_ref}`
              : label;
          },
          pill: true,
        },
      ];
      renderCapabilityTable(body, rows, columns);
    },
  );
}

export function renderCapabilityDetail(
  context, main, project, capabilityType, navigation = {},
) {
  if (capabilityType === "test-machine") {
    if (typeof navigation.setDetailLabel === "function") {
      navigation.setDetailLabel("Test Mac");
    }
    return renderTestMachineDetail(context, main, project);
  }
  main.replaceChildren(el(
    context.document,
    "p",
    "error",
    `unknown capability detail: ${capabilityType}`,
  ));
}
