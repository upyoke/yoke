// Local cross-engine regression; physical iPhone QA remains a release check.
// node universe_search_dialog.visual.mjs PLAYWRIGHT_MODULE OUTPUT_DIR
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
const [modulePath, output] = process.argv.slice(2);
assert(modulePath && output, "Name PLAYWRIGHT_MODULE and OUTPUT_DIR.");
const engines = createRequire(import.meta.url)(modulePath);
const root = fileURLToPath(new URL("../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url));
const styles = [...(await readFile(path.join(root, "index.html"), "utf8"))
  .matchAll(/href="\/assets\/([^\"]+\.css)"/g)].map((m) => m[1]);
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
${styles.map((name) => `<link rel="stylesheet" href="/assets/${name}">`).join("")}
</head><body><main class="universe-app-root"><header class="topbar yoke-app-header"></header></main>
<script type="module">
import { createShellControls } from "/assets/universe_shell_controls.js";
const client={call:async()=>({status:200,envelope:{success:true,result:{rows:[],queries:[]}}})};
const controls=createShellControls({documentNode:document,client,options:{}});
document.querySelector(".topbar").append(controls.search);
window.ready=true;
</script></body></html>`;
const server = createServer(async (req, res) => {
  try {
    if (req.url === "/") { res.setHeader("Content-Type", "text/html"); res.end(html); return; }
    const name = new URL(req.url, "http://localhost").pathname.slice(8);
    assert(!name.includes("/") && !name.includes(".."));
    res.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/css");
    res.end(await readFile(path.join(root, name)));
  } catch (error) { res.statusCode = 500; res.end(String(error)); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
await mkdir(output, { recursive: true });
const measurements = [];
try {
  for (const engine of ["chromium", "webkit"]) {
    const browser = await engines[engine].launch({ headless: true });
    try {
      // The shorter viewport exercises the layout with room taken by a keyboard.
      // It does not simulate Safari's keyboard or replace the operator's phone check.
      for (const width of [320, 390, 768]) for (const height of [844, 400]) {
        const page = await browser.newPage({ viewport: { width, height }, isMobile: true, hasTouch: true });
        try {
          await page.goto(`http://127.0.0.1:${server.address().port}/`);
          await page.waitForFunction(() => window.ready);
          await page.locator(".header-search").tap();
          await page.locator(".header-search-hint").waitFor();
          for (const query of ["", "unbroken-query-".repeat(30)]) {
            await page.locator(".header-search-input").fill(query);
            const data = await page.locator(".header-search-panel").evaluate((panel) => {
              const box = (node) => { const r = node.getBoundingClientRect(); return { left:r.left,right:r.right,width:r.width }; };
              const input = panel.querySelector("input"), close = panel.querySelector(".header-search-close");
              return { panel:box(panel), close:box(close), input:box(input), fontSize:parseFloat(getComputedStyle(input).fontSize),
                focused:document.activeElement===input, viewport:visualViewport.width,
                overflows:[panel,...panel.querySelectorAll(".header-search-field,.header-search-body,.header-search-hint")]
                  .map((node)=>({name:node.className,width:node.clientWidth,scroll:node.scrollWidth,...box(node)})) };
            });
            measurements.push({ engine, width, height, query:query ? "long" : "empty", ...data });
            await writeFile(path.join(output, "measurements.json"), JSON.stringify(measurements, null, 2));
            assert(data.focused, "Search must retain input focus");
            assert(data.panel.left>=-1 && data.panel.right<=data.viewport+1, "Dialog must fit the visual viewport");
            assert(data.close.left>=data.panel.left && data.close.right<=data.panel.right, "Esc must stay fully inside the dialog");
            assert(data.input.right<=data.close.left, "Input must leave room for Esc");
            for (const row of data.overflows) {
              assert(row.scroll<=row.width+1, `${engine} ${width}x${height}: ${row.name} overflows`);
              assert(row.right<=data.viewport+1, `${row.name} extends beyond viewport`);
            }
            assert(data.fontSize>=16, "Focused iPhone input must avoid Safari's sub-16px automatic zoom");
          }
          await page.screenshot({ path:path.join(output, `${engine}-${width}-${height}.png`) });
          await page.locator(".header-search-close").tap();
          assert.equal(await page.locator(".header-search-overlay").evaluate(n=>n.matches(":popover-open")), false);
        } finally { await page.close(); }
      }
    } finally { await browser.close(); }
  }
  console.log("Search dialog fits Chromium and WebKit at phone/tablet widths and reduced heights.");
} finally { await new Promise((resolve) => server.close(resolve)); }
