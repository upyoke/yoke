import {
  el,
} from "./universe_view_support.js";
import {
  qaPanel,
} from "./qa_view_primitives.js";

export function renderExecutionTarget(documentNode, plan) {
  const result = qaPanel(
    documentNode,
    "Execution target",
    null,
    "immutable when cases materialize",
  );
  const target = plan.execution_target;
  if (!target) {
    result.body.appendChild(el(
      documentNode,
      "p",
      "empty qa-target-missing",
      "Not bound — this plan cannot be dispatched.",
    ));
    return result.root;
  }
  const identity = el(documentNode, "div", "qa-target-identity");
  identity.appendChild(el(
    documentNode,
    "strong",
    null,
    `${target.tenant.name} · ${target.project.name}`,
  ));
  identity.appendChild(el(
    documentNode,
    "span",
    null,
    `${target.environment.name} · ${target.environment.id}`,
  ));
  result.body.appendChild(identity);
  const endpoints = target.endpoints || {};
  for (const key of [
    "app_url", "api_url", "installer_url", "release_channel",
  ]) {
    result.body.appendChild(el(
      documentNode,
      "div",
      "qa-target-endpoint",
      `${key.replaceAll("_", " ")}: ${endpoints[key] || "not configured"}`,
    ));
  }
  return result.root;
}
