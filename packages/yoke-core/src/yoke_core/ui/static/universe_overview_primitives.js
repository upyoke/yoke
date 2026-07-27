import { buildUniverseRoute, serializeScope } from "./universe_navigation.js";
import { el, section } from "./universe_view_support.js";
import { OVERVIEW_SECTIONS } from "./universe_views_overview_signals.js";

export const SUMMARY_ROW_LIMIT = 5;
export const STRATEGY_BADGE_LIMIT = 6;
export const SESSION_SUMMARY_ROW_LIMIT = 7;

// The link out of a summary and into the full screen, carrying the scope the
// Overview holds so the destination opens on the same projects.
export function openLink(documentNode, view, scope, label) {
  const link = el(documentNode, "a", "overview-open", `Open ${label} →`);
  link.href = buildUniverseRoute(view, serializeScope(scope));
  return link;
}

// A titled summary panel that links to its full screen. The link is a sibling
// of the body, so a section load replacing the body leaves it in place.
export function summaryPanel(documentNode, title, view, scope, label) {
  const panel = section(documentNode, title);
  panel.classList.add("overview-section");
  panel.setAttribute("id", `overview-${view}`);
  panel.children[1].classList.add("overview-section-body");
  const sectionDefinition = OVERVIEW_SECTIONS.find(([id]) => id === view);
  let detail = null;
  if (sectionDefinition) {
    const heading = panel.children[0].children[0];
    heading.textContent = "";
    heading.classList.add("overview-section-heading");
    heading.appendChild(el(
      documentNode,
      "span",
      "overview-section-icon",
      sectionDefinition[1],
    ));
    heading.appendChild(el(
      documentNode,
      "span",
      "overview-section-title",
      title,
    ));
    detail = el(
      documentNode, "span", "overview-section-detail", sectionDefinition[3],
    );
    panel.children[0].appendChild(detail);
  }
  panel.setDetail = (text) => {
    if (detail) detail.textContent = String(text || "");
  };
  panel.appendChild(openLink(documentNode, view, scope, label));
  return panel;
}

export function overviewMiniRow(documentNode, primary, detail, trailing) {
  const row = el(
    documentNode,
    "div",
    "overview-mini-row overview-compact-row",
  );
  if (primary && typeof primary === "object" && primary.tagName) {
    row.appendChild(primary);
  } else {
    row.appendChild(el(documentNode, "strong", null, String(primary ?? "")));
  }
  if (detail && typeof detail === "object" && detail.tagName) {
    row.appendChild(detail);
  } else {
    row.appendChild(el(
      documentNode,
      "span",
      "secondary-muted",
      String(detail ?? ""),
    ));
  }
  if (trailing && typeof trailing === "object" && trailing.tagName) {
    row.appendChild(trailing);
  } else {
    row.appendChild(el(
      documentNode,
      "span",
      "secondary-muted",
      String(trailing ?? ""),
    ));
  }
  return row;
}

export function overviewTable(documentNode, className, headers) {
  const wrap = el(documentNode, "div", "overview-table-wrap");
  const table = el(documentNode, "table", `overview-table ${className}`);
  const head = el(documentNode, "thead");
  const row = el(documentNode, "tr");
  for (const label of headers) {
    row.appendChild(el(documentNode, "th", null, label));
  }
  head.appendChild(row);
  table.appendChild(head);
  const body = el(documentNode, "tbody");
  table.appendChild(body);
  wrap.appendChild(table);
  return { wrap, body };
}

export function appendCell(documentNode, row, value, className = null) {
  const cell = el(documentNode, "td", className);
  if (value && typeof value === "object" && value.tagName) {
    cell.appendChild(value);
  } else {
    cell.textContent = String(value ?? "");
  }
  row.appendChild(cell);
  return cell;
}

export function routeCell(documentNode, row, label, href, className = null) {
  const cell = el(documentNode, "td", className);
  const link = el(documentNode, "a", "overview-row-link", label || "—");
  link.href = href;
  cell.appendChild(link);
  row.appendChild(cell);
  return cell;
}

export function emptyTableRow(documentNode, body, columnCount, message) {
  const row = el(documentNode, "tr", "overview-empty-row");
  const cell = el(documentNode, "td", "empty", message);
  cell.setAttribute("colspan", String(columnCount));
  row.appendChild(cell);
  body.appendChild(row);
}

function eventCameFromControl(event, row) {
  let target = event.target;
  while (target && target !== row) {
    if (["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "TIME", "CODE"].includes(
      String(target.tagName || "").toUpperCase(),
    )) return true;
    target = target.parentNode;
  }
  return false;
}

export function makeRowNavigable(documentNode, row, href, label) {
  row.tabIndex = 0;
  row.setAttribute("role", "link");
  row.setAttribute("aria-label", `Open ${label}`);
  row.addEventListener("click", (event) => {
    if (eventCameFromControl(event, row)) return;
    documentNode.defaultView.location.hash = href;
  });
  row.addEventListener("keydown", (event) => {
    if (eventCameFromControl(event, row)) return;
    if (!["Enter", " "].includes(event.key)) return;
    if (typeof event.preventDefault === "function") event.preventDefault();
    documentNode.defaultView.location.hash = href;
  });
}

export function destinationHref(view, scope) {
  return buildUniverseRoute(view, serializeScope(scope));
}

export function projectDisplay(projects, value) {
  const key = String(value || "");
  const project = projects.find((row) =>
    [row.id, row.slug].some((candidate) => String(candidate) === key));
  if (!project) return key || "—";
  return [project.emoji, project.slug || project.name].filter(Boolean).join(" ");
}

export function ageTone(value) {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "unknown";
  const ageHours = Math.max(0, Date.now() - timestamp) / 3_600_000;
  if (ageHours < 6) return "fresh";
  if (ageHours < 24) return "day";
  if (ageHours < 72) return "three-days";
  if (ageHours < 168) return "week";
  return "older";
}
