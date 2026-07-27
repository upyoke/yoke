import {
  callFunction,
  el,
  statePill,
} from "./universe_view_support.js";

export const machineSecretNotes = {
  ssh_private_key: "executor subprocess only",
  sudo_password: "used only by registered host-baseline operations",
  screen_control_token: "Terminal automation bridge",
};

export function orderedMachineSecrets(secrets) {
  const order = new Map(
    Object.keys(machineSecretNotes).map((key, index) => [key, index]),
  );
  return [...(secrets || [])].sort((left, right) => {
    const leftOrder = order.get(left.key);
    const rightOrder = order.get(right.key);
    if (leftOrder === undefined && rightOrder === undefined) return 0;
    if (leftOrder === undefined) return 1;
    if (rightOrder === undefined) return -1;
    return leftOrder - rightOrder;
  });
}

function rejectedCallMessage(error, fallback) {
  if (error instanceof Error && error.message) return error.message;
  const detail = String(error ?? "").trim();
  return detail || fallback;
}

export function machineSettingsDialog(context, detail, close, saved) {
  const documentNode = context.document;
  const overlay = el(documentNode, "div", "test-machine-overlay");
  const dialog = el(documentNode, "section", "test-machine-dialog");
  overlay.addEventListener("click", close);
  dialog.addEventListener("click", (event) => event.stopPropagation());
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", "Edit Test Mac settings");
  dialog.appendChild(el(documentNode, "h2", null, "Edit Test Mac"));
  dialog.appendChild(el(
    documentNode,
    "p",
    "muted",
    "Only non-secret project capability settings are saved here. Secret values never enter the browser.",
  ));
  const fields = el(documentNode, "div", "test-machine-fields");
  const inputs = {};
  for (const [key, label] of [
    ["resource_name", "Resource name"],
    ["host", "Host"],
    ["user", "User"],
    ["operating_notes", "Operating notes"],
  ]) {
    const wrapper = el(documentNode, "label", null, label);
    const input = el(documentNode, "input");
    input.value = detail.settings[key] || "";
    wrapper.appendChild(input);
    fields.appendChild(wrapper);
    inputs[key] = input;
  }
  dialog.appendChild(fields);
  const credentials = el(documentNode, "div", "test-machine-dialog-secrets");
  credentials.appendChild(el(documentNode, "h3", null, "Credential references"));
  credentials.appendChild(el(
    documentNode,
    "p",
    "muted",
    "Presence is visible here; replacement happens through the registered terminal surface with --value-stdin, so raw values never render or enter browser history.",
  ));
  for (const secret of orderedMachineSecrets(detail.secrets)) {
    const row = el(documentNode, "div", "test-machine-command");
    const identity = el(
      documentNode, "div", "test-machine-command-identity",
    );
    identity.appendChild(el(documentNode, "strong", null, secret.key));
    const state = statePill(
      documentNode, secret.stored ? "stored" : "missing",
    );
    if (state) identity.appendChild(state);
    row.appendChild(identity);
    row.appendChild(el(
      documentNode,
      "small",
      null,
      machineSecretNotes[secret.key] || "executor-only credential",
    ));
    row.appendChild(el(
      documentNode,
      "code",
      null,
      `yoke projects capability secret set --project ${detail.project} --cap-type test-machine --key ${secret.key} --value-stdin`,
    ));
    credentials.appendChild(row);
  }
  dialog.appendChild(credentials);
  const footer = el(documentNode, "div", "test-machine-dialog-footer");
  footer.appendChild(el(
    documentNode,
    "p",
    "muted",
    "Host baselines stay read-only here: fresh-host and shell-preconfigured are registered executor operations, not user-authored instructions.",
  ));
  const error = el(
    documentNode, "p", "test-machine-settings-error error",
  );
  error.setAttribute("role", "alert");
  error.setAttribute("aria-live", "polite");
  error.hidden = true;
  footer.appendChild(error);
  const actions = el(documentNode, "div", "test-machine-dialog-actions");
  const cancel = el(documentNode, "button", "btn", "Cancel");
  cancel.type = "button";
  cancel.addEventListener("click", close);
  actions.appendChild(cancel);
  const save = el(documentNode, "button", "btn primary", "Save non-secret settings");
  save.type = "button";
  save.addEventListener("click", async () => {
    error.textContent = "";
    error.hidden = true;
    save.disabled = true;
    save.textContent = "Saving…";
    const fail = (message) => {
      save.disabled = false;
      save.textContent = "Save non-secret settings";
      error.textContent = message;
      error.hidden = false;
    };
    let result;
    try {
      result = await callFunction(
        context.client,
        "test_machine.settings_replace",
        {
          project: detail.project,
          settings: Object.fromEntries(
            Object.entries(inputs).map(([key, input]) => [key, input.value]),
          ),
          base_settings: detail.settings_token,
        },
      );
    } catch (callError) {
      fail(rejectedCallMessage(
        callError,
        "Could not save non-secret settings.",
      ));
      return;
    }
    if (!result.envelope.success) {
      fail(
        result.envelope?.error?.message ||
          "Could not save non-secret settings.",
      );
      return;
    }
    saved();
  });
  actions.appendChild(save);
  footer.appendChild(actions);
  dialog.appendChild(footer);
  overlay.appendChild(dialog);
  return overlay;
}
