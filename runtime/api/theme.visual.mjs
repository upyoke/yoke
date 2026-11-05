// Committed source proof for system themes, host overrides and text contrast.
// node theme.visual.mjs PLAYWRIGHT_MODULE OUTPUT_DIR
// Optional YOKE_REVIEW_URL + YOKE_REVIEW_ROUTES capture populated review pages.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const [modulePath, output] = process.argv.slice(2);
assert(modulePath && output, "Name PLAYWRIGHT_MODULE and OUTPUT_DIR.");
const { chromium } = createRequire(import.meta.url)(modulePath);
const checkout = fileURLToPath(new URL("../../", import.meta.url));
const root = path.join(checkout, "packages/yoke-core/src/yoke_core/ui/static");
const git = (...args) => execFileSync("git", ["-C", checkout, ...args], { encoding: "utf8" }).trim();
const head = git("rev-parse", "HEAD");
assert.equal(git("status", "--porcelain"), "", "Commit the capture source first.");
const tokens = ["ink", "ink-2", "muted", "accent", "accent-2", "good", "warn", "crit",
  "run", "idle", "park", "stage-waiting", "stage-hold", "stage-ready", "stage-active",
  "stage-release", "stage-done"];
const html = `<!doctype html><html><head><link rel="stylesheet" href="/theme.css"></head>
<body style="background:var(--yoke-bg);color:var(--yoke-ink)">
<h1>Steel orange theme proof</h1><div id="mark"></div>
<button style="background:var(--yoke-accent-fill);color:var(--yoke-accent-fill-ink)">Filled control</button>
${tokens.map(t => `<p style="color:var(--yoke-${t})">${t}</p>`).join("")}
<footer>Committed source fixture; no live universe</footer></body></html>`;
const server = createServer(async (request, response) => {
  try {
    if (request.url === "/") {
      response.setHeader("Content-Type", "text/html"); response.end(html); return;
    }
    assert.equal(request.url, "/theme.css");
    response.setHeader("Content-Type", "text/css");
    response.end(await readFile(path.join(root, "theme.css")));
  } catch (error) { response.statusCode = 500; response.end(String(error)); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = { head_sha: head, themes: [], contrast: [], captures: [] };
function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(v => parseInt(v, 16) / 255)
    .map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return channels.reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
}
function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}
const review = process.env.YOKE_REVIEW_URL;
const routes = JSON.parse(process.env.YOKE_REVIEW_ROUTES || "null");
assert(!review || routes, "Supply named board, item, run and sessions review routes.");
try {
  for (const system of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: system });
    const page = await context.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.locator("#mark").evaluate((n, svg) => { n.innerHTML = svg; },
      await readFile(path.join(root, "yoke-wordmark.svg"), "utf8"));
    for (const forced of [null, "light", "dark"]) {
      await page.evaluate(theme => {
        if (theme) document.documentElement.dataset.theme = theme;
        else delete document.documentElement.dataset.theme;
      }, forced);
      const theme = forced || system;
      const values = await page.evaluate(names => {
        const style = getComputedStyle(document.documentElement);
        return Object.fromEntries(["bg", "surface", "accent-fill", "accent-fill-ink", ...names]
          .map(name => [name, style.getPropertyValue(`--yoke-${name}`).trim()])
          .concat([["scheme", style.colorScheme], ["wordmark", getComputedStyle(document.querySelector("#mark g:last-child")).fill],
            ["inkColor", getComputedStyle(document.body).color]]));
      }, tokens);
      assert.equal(values.bg, theme === "light" ? "#f7f8fa" : "#101418");
      assert.equal(values.scheme, theme);
      assert.equal(values.wordmark, values.inkColor, "Inline wordmark must inherit theme ink.");
      report.themes.push({ system, forced, effective: theme, values });
      if (forced === null) {
        for (const token of tokens) for (const background of ["bg", "surface"]) {
          const ratio = contrast(values[token], values[background]);
          report.contrast.push({ theme, token, background, ratio: Number(ratio.toFixed(3)) });
          assert(ratio >= 4.5, `${theme} ${token} on ${background}: ${ratio}`);
        }
        assert(contrast(values["accent-fill"], values["accent-fill-ink"]) >= 4.5);
      }
    }
    if (review) {
      const identity = new URL("/served-build", review); identity.search = new URL(review).search;
      assert.equal((await (await fetch(identity)).text()).trim(), head);
      for (const name of ["board", "item", "run", "sessions"]) {
        assert(routes[name], `Supply the ${name} review route.`);
        const url = new URL(routes[name], review); url.search = new URL(review).search;
        await page.goto(url.href);
        await page.locator(".universe-app-root").waitFor();
        await page.waitForFunction(() => !/Loading…/.test(document.body.innerText));
        if (name === "run" && process.env.YOKE_REVIEW_RUN_FIXTURE === "1") {
          await page.evaluate(async sha => {
            const { renderRunDetailView } = await import("/assets/universe_views_run_detail.js");
            const row = { id: "source-review", project: "Example project", flow: "Production release",
              status: "executing", current_stage: "verification", target_environment: "prod",
              release_lineage: sha, stages: [{ name: "Build", state: "complete" },
                { name: "Verification", state: "active" }, { name: "Deploy", state: "pending" }] };
            const context = { document, projects: () => [], isMounted: () => true,
              client: { call: async () => ({ status: 200, envelope: { success: true,
                result: { rows: [row] } } }) } };
            const host = document.querySelector(".view-host");
            if (!host) throw new Error("Missing review view host");
            await renderRunDetailView(context, host, null, row.id);
            const note = document.createElement("p");
            note.textContent = "Source rendering fixture; no deployment run was created.";
            host.appendChild(note);
          }, head);
        }
        await page.evaluate(() => document.fonts.ready);
        const filename = `${name}-1440-${system}.png`;
        await page.screenshot({ path: path.join(output, filename), fullPage: true });
        report.captures.push({ name, theme: system, filename,
          source_fixture: name === "run" && process.env.YOKE_REVIEW_RUN_FIXTURE === "1" });
      }
      assert.equal((await (await fetch(identity)).text()).trim(), head);
    }
    await context.close();
  }
  await writeFile(path.join(output, "theme-proof.json"), JSON.stringify(report, null, 2));
  console.table(report.contrast);
  console.log(`Verified six theme combinations and ${report.contrast.length} text contrasts on ${head}`);
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
