import { callFunction, el } from "./universe_view_support.js";

export async function readCase(context, functionId, payload, target) {
  const result = await callFunction(context.client, functionId, payload, target);
  if (result.status === 200 && result.envelope.success) return result.envelope.result || {};
  const error = new Error(result.envelope?.error?.message || "QA details are unavailable.");
  error.callResult = result;
  throw error;
}

// Ancillary evidence can fail while the case and its executions remain readable.
// Retain that distinction and let the page offer a retry alongside known facts.
export async function readOptionalCase(context, ...args) {
  try {
    return await readCase(context, ...args);
  } catch (error) {
    context.caseReadFailures?.push(error);
    return null;
  }
}

export function retryCaseButton(context, retry) {
  const button = el(context.document, "button", "item-button qa-case-retry", "Retry");
  button.type = "button";
  button.addEventListener("click", retry);
  return button;
}
