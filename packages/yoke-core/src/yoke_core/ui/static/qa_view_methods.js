import { el, statePill } from "./universe_view_support.js";
import {
  capabilityLabel,
  detailHead,
  keyValuePanel,
  loadProjectCalls,
  methodGroupLabel,
  methodIcon,
  showFailure,
  sourceLabel,
} from "./qa_view_primitives.js";

const METHOD_ORDER = [
  "command",
  "browser-check",
  "browser-inspection",
  "terminal-check",
  "terminal-inspection",
  "machine-state-check",
];

function methodOrder(method) {
  const index = METHOD_ORDER.indexOf(method.id);
  return index < 0 ? METHOD_ORDER.length : index;
}

function combinedMethods(callResults) {
  const methods = new Map();
  for (const result of callResults) {
    for (const row of result.envelope.result?.rows || []) {
      const existing = methods.get(row.id);
      if (!existing) {
        methods.set(row.id, {
          ...row,
          used_by_plan_count: Number(row.used_by_plan_count || 0),
          capability_states: new Set([row.capability_state]),
        });
        continue;
      }
      existing.used_by_plan_count += Number(row.used_by_plan_count || 0);
      existing.capability_states.add(row.capability_state);
    }
  }
  return [...methods.values()]
    .map((method) => ({
      ...method,
      capability_state: method.capability_states.size === 1
        ? [...method.capability_states][0] : "mixed",
    }))
    .sort((left, right) => (
      methodOrder(left) - methodOrder(right)
      || left.name.localeCompare(right.name)
    ));
}

function methodCard(documentNode, method, open) {
  const card = el(documentNode, "button", "qa-method-card");
  card.type = "button";
  card.addEventListener("click", () => open(method));
  const top = el(documentNode, "span", "qa-method-top");
  top.appendChild(el(
    documentNode, "span", "qa-method-icon", methodIcon(method.id),
  ));
  const identity = el(documentNode, "span", "qa-method-identity");
  identity.appendChild(el(documentNode, "strong", null, method.name));
  const count = method.used_by_plan_count;
  identity.appendChild(el(
    documentNode, "span", "qa-method-usage",
    `used by ${count} ${count === 1 ? "plan" : "plans"}`,
  ));
  top.appendChild(identity);
  top.appendChild(el(
    documentNode, "span",
    `qa-source ${method.source_kind}`, sourceLabel(method),
  ));
  const description = el(
    documentNode, "span", "qa-method-description", method.description,
  );
  const foot = el(documentNode, "span", "qa-method-foot");
  foot.appendChild(el(documentNode, "span", null, "capability"));
  foot.appendChild(el(
    documentNode, "strong", null,
    capabilityLabel(method.required_capability_kind),
  ));
  const state = statePill(
    documentNode,
    String(method.capability_state || "").replaceAll("_", " "),
  );
  if (state) foot.appendChild(state);
  card.appendChild(top);
  card.appendChild(description);
  card.appendChild(foot);
  return card;
}

function renderRoster(documentNode, host, methods, open) {
  const stack = el(documentNode, "div", "qa-method-groups");
  const groups = new Map();
  for (const method of methods) {
    const key = method.required_capability_kind || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(method);
  }
  for (const [kind, rows] of groups) {
    stack.appendChild(el(
      documentNode, "p", "qa-group-label",
      methodGroupLabel(kind, rows[0]?.capability_state),
    ));
    const catalog = el(documentNode, "div", "qa-method-catalog");
    for (const method of rows) {
      catalog.appendChild(methodCard(documentNode, method, open));
    }
    stack.appendChild(catalog);
  }
  const explainer = el(documentNode, "section", "panel qa-method-sources");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(
    documentNode, "h2", null, "How methods enter this project",
  ));
  const body = el(documentNode, "div", "panel-body qa-source-grid");
  for (const [title, copy] of [
    ["Built in", "Ships with Yoke and updates with core."],
    [
      "Registered by Pack",
      "Definition plus approved executor integration, managed on Packs.",
    ],
    [
      "Project local",
      "A project-owned definition over registered executors.",
    ],
  ]) {
    const item = el(documentNode, "div", "qa-source-note");
    item.appendChild(el(documentNode, "strong", null, title));
    item.appendChild(el(documentNode, "span", null, copy));
    body.appendChild(item);
  }
  explainer.appendChild(header);
  explainer.appendChild(body);
  stack.appendChild(explainer);
  host.replaceChildren(stack);
}

function renderMethodDetail(documentNode, host, method, back) {
  const source = sourceLabel(method);
  const subtitle = method.required_capability_kind
    ? `${source} method · requires ${
      capabilityLabel(method.required_capability_kind)
    }`
    : `${source} method`;
  const content = el(documentNode, "div", "qa-detail-grid");
  content.appendChild(keyValuePanel(documentNode, "Contract", [
    ["Executor", method.executor_id],
    [
      "Capability",
      method.required_capability_kind
        ? `${capabilityLabel(method.required_capability_kind)} · ${
          String(method.capability_state).replaceAll("_", " ")
        }`
        : "none — a checkout is enough",
    ],
    ["Verdict", `${method.verdict_path} — ${method.verdict_contract}`],
    ["Evidence", method.evidence_contract],
    ["Concurrency", method.concurrency_mode],
    ["Source", source],
    ["Success policy", method.success_policy_id],
  ]));
  const used = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, "Used by plans"));
  const body = el(documentNode, "div", "panel-body qa-plan-links");
  if (!method.plans?.length) {
    body.appendChild(el(documentNode, "p", "empty", "not used by a plan yet"));
  }
  for (const plan of method.plans || []) {
    const row = el(documentNode, "div", "qa-plan-link");
    const copy = el(documentNode, "span");
    copy.appendChild(el(documentNode, "strong", null, plan.slug));
    copy.appendChild(el(
      documentNode, "small", null, plan.case_keys.join(" · "),
    ));
    row.appendChild(copy);
    row.appendChild(el(
      documentNode, "span", "qa-project", plan.project,
    ));
    body.appendChild(row);
  }
  used.appendChild(header);
  used.appendChild(body);
  content.appendChild(used);
  host.replaceChildren(
    detailHead(documentNode, method.name, subtitle, back),
    content,
  );
}

export async function renderQaMethods(context, main, scope) {
  const documentNode = context.document;
  const loading = el(documentNode, "p", "empty", "loading methods…");
  main.replaceChildren(loading);
  const { callResults, failed } = await loadProjectCalls(
    context, scope, "qa.method.list", {},
  );
  if (!context.isMounted()) return;
  if (failed) {
    showFailure(documentNode, main, failed);
    return;
  }
  const methods = combinedMethods(callResults);
  const showRoster = () => renderRoster(
    documentNode,
    main,
    methods,
    async (method) => {
      main.replaceChildren(el(
        documentNode, "p", "empty", `loading ${method.name}…`,
      ));
      const detailCalls = await loadProjectCalls(
        context, scope, "qa.method.get", { method_id: method.id },
      );
      if (!context.isMounted()) return;
      if (detailCalls.failed) {
        showFailure(documentNode, main, detailCalls.failed);
        return;
      }
      const details = detailCalls.callResults.map(
        (result) => result.envelope.result.method,
      );
      const plans = details.flatMap((detail) => detail.plans || []);
      renderMethodDetail(
        documentNode,
        main,
        { ...details[0], plans },
        showRoster,
      );
    },
  );
  showRoster();
}
