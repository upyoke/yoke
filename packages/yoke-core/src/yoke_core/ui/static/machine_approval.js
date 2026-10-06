// Shared workbench page: hosts provide the normal function client; their
// pending-code store decides where the code binds to an organization.
import { callFunction, el, labelledField, loadSection, section } from "./universe_view_support.js";

export function renderMachineApproval(context, main, _scope, code) {
  const documentNode = context.document;
  const panel = section(documentNode, "Connect your machine");
  main.replaceChildren(panel);
  if (!code) {
    panel.renderEnvelope({}, (body) => {
      const form = el(documentNode, "form");
      const input = el(documentNode, "input");
      input.required = true;
      input.maxLength = 32;
      input.autocomplete = "off";
      const submit = el(documentNode, "button", "button", "Continue");
      submit.type = "submit";
      form.appendChild(labelledField(documentNode, "One-time code from your CLI", input));
      form.appendChild(submit);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        context.navigate(`/machine-approval/${encodeURIComponent(input.value.trim())}`);
      });
      body.appendChild(form);
    });
    return;
  }
  loadSection(context, panel, "machine_authorization.get", { code }, (body, result) => {
    const authorization = result.envelope.result.authorization;
    body.appendChild(el(documentNode, "p", null, "Approve only a code shown by yoke connect on your own machine."));
    body.appendChild(el(documentNode, "p", null, `One-time code: ${authorization.code}`));
    body.appendChild(el(documentNode, "p", null, `Machine: ${authorization.machine || "Connecting machine"}`));
    if (authorization.machine_id) body.appendChild(el(documentNode, "p", "muted", `Machine ID: ${authorization.machine_id}`));
    body.appendChild(el(documentNode, "p", "muted", `Expires: ${authorization.expires_at}`));
    const status = el(documentNode, "p");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    body.appendChild(status);
    if (authorization.decision) {
      status.textContent = authorization.decision === "approve"
        ? "Machine approved. Return to your CLI to finish connecting."
        : "Machine denied. Start a fresh connection in your CLI.";
      return;
    }
    const buttons = [
      ["approve", "Approve my machine"], ["deny", "Deny"],
    ].map(([action, label]) => {
      const button = el(documentNode, "button", "button", label);
      button.type = "button";
      button.addEventListener("click", async () => {
        buttons.forEach((node) => { node.disabled = true; });
        status.textContent = "Recording your decision…";
        try {
          const reply = await callFunction(context.client, "machine_authorization.resolve", { code, action });
          if (!context.isMounted() || !main.contains(body)) return;
          if (!reply.envelope?.success) throw new Error(reply.envelope?.error?.message || "Approval failed; retry or start a fresh connection code.");
          status.textContent = action === "approve"
            ? "Machine approved. Return to your CLI to finish connecting."
            : "Machine denied. Start a fresh connection in your CLI.";
          buttons.forEach((node) => body.removeChild(node));
        } catch (error) {
          if (!context.isMounted() || !main.contains(body)) return;
          status.textContent = `${error.message || error} Retry, or start a fresh connection code.`;
          buttons.forEach((node) => { node.disabled = false; });
        }
      });
      body.appendChild(button);
      return button;
    });
  });
}
