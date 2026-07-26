import {
  callFunction,
  el,
  renderError,
  scopeBuckets,
  settledScopedCalls,
  statePill,
} from "./universe_view_support.js";

const METHOD_ICONS = {
  command: "⌥",
  "browser-check": "◎",
  "browser-inspection": "◉",
  "terminal-check": "⌨",
  "terminal-inspection": "⌘",
  "machine-state-check": "≡",
};

const CAPABILITY_LABELS = {
  "browser-control": "Browser control",
  "test-machine": "Test Mac",
};

export function methodIcon(methodId) {
  return METHOD_ICONS[methodId] || "◉";
}

export function capabilityLabel(kind) {
  return kind ? (CAPABILITY_LABELS[kind] || kind) : "none";
}

export function sourceLabel(method) {
  if (method.source_kind === "built_in") return "built-in";
  if (method.source_kind === "pack") {
    return method.source_ref ? `Pack · ${method.source_ref}` : "Pack";
  }
  return "project local";
}

export function detailHead(documentNode, title, subtitle, back) {
  const head = el(documentNode, "div", "qa-detail-head");
  const backButton = el(documentNode, "button", "qa-back", "← QA");
  backButton.type = "button";
  backButton.addEventListener("click", back);
  const text = el(documentNode, "div", "qa-detail-heading");
  text.appendChild(el(documentNode, "h2", null, title));
  text.appendChild(el(documentNode, "p", null, subtitle));
  head.appendChild(backButton);
  head.appendChild(text);
  return head;
}

export function keyValuePanel(documentNode, title, rows) {
  const panel = el(documentNode, "section", "panel qa-contract");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, title));
  panel.appendChild(header);
  const list = el(documentNode, "dl", "qa-key-values");
  for (const [label, value] of rows) {
    list.appendChild(el(documentNode, "dt", null, label));
    const cell = el(documentNode, "dd");
    if (value && value.nodeType) cell.appendChild(value);
    else cell.textContent = String(value ?? "—");
    list.appendChild(cell);
  }
  panel.appendChild(list);
  return panel;
}

export function outcomeNode(documentNode, outcome, degradedReason = null) {
  const wrap = el(documentNode, "span", "qa-outcome");
  const display = String(outcome || "queued").replaceAll("_", " ");
  const pill = statePill(documentNode, display);
  if (pill) wrap.appendChild(pill);
  if (degradedReason) {
    wrap.appendChild(el(
      documentNode, "span", "qa-degraded", "capture degraded",
    ));
    wrap.title = degradedReason;
  }
  return wrap;
}

export function qaPanel(documentNode, title, count = null) {
  const root = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  const heading = el(documentNode, "h2", null, title);
  if (count !== null) {
    heading.appendChild(el(
      documentNode, "span", "panel-count", `· ${count}`,
    ));
  }
  header.appendChild(heading);
  root.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  root.appendChild(body);
  return { root, body };
}

export function projectCalls(context, scope, functionId, payload = {}) {
  return scopeBuckets(scope, context.projects(), true).map((project) => ({
    functionId,
    payload: { ...payload, project },
  }));
}

export async function loadProjectCalls(context, scope, functionId, payload) {
  return settledScopedCalls(
    context,
    projectCalls(context, scope, functionId, payload),
  );
}

export async function oneProjectCall(
  context, functionId, project, payload = {},
) {
  try {
    return await callFunction(
      context.client, functionId, { ...payload, project },
    );
  } catch (error) {
    return {
      status: 0,
      envelope: { success: false, error: { message: String(error) } },
    };
  }
}

export function showFailure(documentNode, host, callResult) {
  const panel = el(documentNode, "section", "panel");
  const body = el(documentNode, "div", "panel-body");
  panel.appendChild(body);
  renderError(body, callResult);
  host.replaceChildren(panel);
}

export function methodGroupLabel(kind, state) {
  if (!kind) return "requires nothing — a checkout is enough";
  const base = `requires ${capabilityLabel(kind)}`;
  const suffix = state ? ` · ${String(state).replaceAll("_", " ")}` : "";
  return kind === "test-machine"
    ? `${base}${suffix} · serial lease`
    : `${base}${suffix}`;
}
