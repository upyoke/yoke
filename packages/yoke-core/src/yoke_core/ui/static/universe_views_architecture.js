// The Architecture screen: one project's declared map and how well the
// tree honors it. A single read (`project_structure.architecture_health.get`)
// serves both panels — Health on top (coverage and current violations),
// the Map underneath (layers, areas, gateways) — so the page and the
// Doctor rows can never disagree: they fold the same computed facts.
// Read-only: the map is edited through the project-structure patch
// surface, and an undeclared map gets the draft recipe rather than a
// dead control.

import {
  el,
  loadSection,
  section,
} from "./universe_view_support.js";

function factsTable(documentNode, rows) {
  const table = el(documentNode, "table", "items kv");
  for (const row of rows) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "th", null, row.label));
    const cell = el(documentNode, "td");
    if (row.code) cell.appendChild(el(documentNode, "code", null, String(row.value)));
    else cell.textContent = String(row.value ?? "");
    tr.appendChild(cell);
    table.appendChild(tr);
  }
  return table;
}

function renderUndeclared(body) {
  const documentNode = body.ownerDocument;
  body.appendChild(el(
    documentNode, "p", "empty",
    "This project declares no architecture map yet. A map names the " +
      "project's areas and kinds of code, which dependency directions " +
      "are allowed, and which gateway modules own cross-cutting " +
      "concerns; every file the map covers is classified " +
      "automatically whenever the file inventory syncs.",
  ));
  const line = el(
    documentNode, "p", "fact-line", "Propose one from the tree with ",
  );
  line.appendChild(el(
    documentNode, "code", null,
    "yoke project-structure architecture-draft get --project <slug>",
  ));
  line.appendChild(el(
    documentNode, "span", null,
    " , review the draft, then apply it with the project-structure " +
      "patch surface.",
  ));
  body.appendChild(line);
}

function renderHealthFacts(body, health) {
  const documentNode = body.ownerDocument;
  body.appendChild(factsTable(documentNode, [
    {
      label: "coverage",
      value: `${health.coverage_pct}% of ${health.python_paths} python files`,
    },
    { label: "classified", value: health.classified },
    { label: "exempt", value: health.exempt },
    { label: "unclassified", value: health.unclassified },
    { label: "forbidden edges", value: health.forbidden_edge_count },
    { label: "guarded-import violations", value: health.cross_cutting_count },
  ]));
  const examples = [
    ...(health.forbidden_edge_examples || []).map((example) => (
      `${example.path}: ${example.source_layer} → ` +
      `${example.imported_layer} via ${example.imported_module}`
    )),
    ...(health.cross_cutting_examples || []).map((example) => (
      `${example.path}: ${example.guarded_symbol} outside ` +
      `'${example.entrypoint}'`
    )),
  ];
  if (!examples.length) {
    body.appendChild(el(
      documentNode, "p", "empty", "no current violations",
    ));
    return;
  }
  const list = el(documentNode, "ul", "fact-list");
  for (const text of examples) {
    const item = el(documentNode, "li");
    item.appendChild(el(documentNode, "code", null, text));
    list.appendChild(item);
  }
  body.appendChild(list);
}

function renderMapFacts(body, health) {
  const documentNode = body.ownerDocument;
  const layers = health.layers || [];
  const layerTable = el(documentNode, "table", "items kv");
  for (const layer of layers) {
    const tr = el(documentNode, "tr");
    tr.appendChild(el(documentNode, "th", null, layer.id));
    const deps = (layer.may_depend_on || []).join(", ");
    tr.appendChild(el(
      documentNode, "td", null,
      deps ? `may depend on ${deps}` : "depends on nothing",
    ));
    layerTable.appendChild(tr);
  }
  body.appendChild(el(documentNode, "h3", null, "Layers"));
  body.appendChild(layerTable);

  body.appendChild(el(documentNode, "h3", null, "Areas"));
  const domains = health.domains || [];
  if (domains.length) {
    const domainTable = el(documentNode, "table", "items kv");
    for (const domain of domains) {
      const tr = el(documentNode, "tr");
      tr.appendChild(el(documentNode, "th", null, domain.id));
      tr.appendChild(el(
        documentNode, "td", null, `${domain.pattern_count} pattern(s)`,
      ));
      domainTable.appendChild(tr);
    }
    body.appendChild(domainTable);
  } else {
    body.appendChild(el(
      documentNode, "p", "empty",
      "no area patterns yet — the map grows as the tree does",
    ));
  }

  body.appendChild(el(documentNode, "h3", null, "Gateways"));
  const entrypoints = health.entrypoints || [];
  if (entrypoints.length) {
    const line = el(documentNode, "p", "fact-line");
    entrypoints.forEach((name, index) => {
      if (index) line.appendChild(el(documentNode, "span", null, ", "));
      line.appendChild(el(documentNode, "code", null, name));
    });
    body.appendChild(line);
  } else {
    body.appendChild(el(
      documentNode, "p", "empty", "no cross-cutting gateways declared",
    ));
  }
}

export function renderArchitectureView(context, main, scope) {
  const documentNode = context.document;
  const healthPanel = section(documentNode, "Health");
  main.replaceChildren(healthPanel);
  loadSection(
    context, healthPanel,
    "project_structure.architecture_health.get",
    { project: scope },
    (body, callResult) => {
      const health = (callResult.envelope.result || {}).health || {};
      if (!health.declared) {
        renderUndeclared(body);
        return;
      }
      renderHealthFacts(body, health);
      const mapPanel = section(documentNode, "The declared map");
      main.appendChild(mapPanel);
      mapPanel.renderEnvelope(
        callResult, (panelBody) => renderMapFacts(panelBody, health),
      );
    },
  );
}
