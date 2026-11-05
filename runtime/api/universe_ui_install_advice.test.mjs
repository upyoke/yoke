import assert from "node:assert/strict";
import test from "node:test";
import { allNodes, byClass, response, visibleText } from "./universe_ui_dom_test_support.mjs";
import {
  activationAnswer, activationClient, mountWorkbench, wizardSubmodules,
} from "./universe_ui_onboarding_test_support.mjs";

for (const origin of ["https://api.stage.upyoke.com", "https://api.upyoke.com"]) {
  test(`hosted onboarding renders the engine install authority ${origin}`, async (t) => {
    const originalFetch = globalThis.fetch;
    t.after(() => { globalThis.fetch = originalFetch; });
    globalThis.fetch = () => response(200, {});
    const answer = activationAnswer({
      states: { finish_installation_wizard: "in_progress" },
      extras: { finish_installation_wizard: { submodules: wizardSubmodules() } },
    });
    answer.install_command = `curl -fsSL ${origin}/install | sh`;
    const { root, mounted } = await mountWorkbench(
      activationClient(answer), { data: { portability: { mode: "hosted" } } },
    );
    const webFirst = byClass(root, "web-first")[0];
    const codes = allNodes(webFirst).filter((n) => n.tagName === "CODE");
    const host = new URL(origin).host.replace(/^api\./, "");
    assert.deepEqual(codes.map((code) => code.textContent), [
      `install ${host}`, answer.install_command,
    ]);
    assert.ok(visibleText(webFirst).includes(
      `Tell Claude Code, Codex, or Cursor: install ${host}`,
    ));
    assert.ok(visibleText(webFirst).includes(`Your agent runs: ${answer.install_command}`));
    assert.equal(codes[1].parentNode.tagName, "SMALL");
    mounted.unmount();
  });
}
