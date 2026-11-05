// Source fixtures exercise the real Inbox renderer at desktop and phone widths.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const [playwrightModule, output] = process.argv.slice(2);
assert(playwrightModule && output, "Name PLAYWRIGHT_MODULE and OUTPUT_DIR.");
const { chromium } = createRequire(import.meta.url)(playwrightModule);
const root = fileURLToPath(new URL("../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url));
const head = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
assert.equal(execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }).trim(), "", "Commit the capture source first.");
const entry = await readFile(path.join(root, "index.html"), "utf8");
const styles = [...entry.matchAll(/href="(?:\.\/|\/)assets\/([^\"]+\.css)"/g)].map((match) => match[1]);
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
${styles.map((name) => `<link rel="stylesheet" href="/assets/${name}">`).join("\n")}
<style>body{margin:0;background:var(--yoke-bg);color:var(--yoke-ink);font-family:var(--yoke-font-sans)}
main{max-width:960px;margin:auto;padding:16px}footer{font-size:11px;overflow-wrap:anywhere}</style></head>
<body><main class="universe-app-root"><h1>Inbox</h1><div id="inbox"></div>
<footer>Source fixture · no live universe · ${head}</footer></main><script type="module">
import {renderInboxView} from '/assets/universe_views_inbox.js';
let row={id:7,kind:'operator_question',status:'pending',project_id:10,
requesting_session_id:'sample-worker',requesting_session_label:'Morgan · Codex',
actions:['blue','green','freeform'],subject_context:{question:'Which color should the header use?',
context:'The current header uses **blue**. The alternative improves contrast.',
options:[{id:'blue',label:'Keep blue',detail:'Matches the existing header'},{id:'green',label:'Use green'}],
recommended_option:'blue',allow_freeform:true}};
window.calls=[];
const client={async call(request){
window.calls.push(request);
if(request.function==='decision_requests.resolve'){
row={...row,status:'resolved',decided_by_you:true,actions:[],resolution_action:request.payload.action,
resolution_note:request.payload.note,your_decision:{action:request.payload.action,note:request.payload.note}};
return {status:200,envelope:{success:true,result:{request:row}}};}
return {status:200,envelope:{success:true,result:{needs_decision:[row],messages:[]}}};}};
renderInboxView({document,client,isMounted:()=>true,projects:()=>[{id:10,slug:'example'}]},document.getElementById('inbox'),'all');
window.proofReady=true;
</script></body></html>`;
const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname === "/") { response.setHeader("Content-Type", "text/html"); response.end(html); return; }
    const name = pathname.slice("/assets/".length);
    assert(pathname.startsWith("/assets/") && !name.includes("/") && !name.includes(".."));
    response.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/css");
    response.end(await readFile(path.join(root, name)));
  } catch (error) { response.statusCode = 500; response.end(String(error)); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const captures = [];
try {
  for (const width of [1440, 375]) for (const answer of ["option", "freeform"]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.locator(".inbox-question-card").waitFor();
    assert.match(await page.locator(".inbox-question-option").first().textContent(), /Recommended/);
    await page.locator(".inbox-question-context summary").click();
    assert.equal(await page.locator(".inbox-question-context strong").textContent(), "blue");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(overflow, false, "Question card must fit phone width.");
    const heights = await page.locator(".inbox-question-option, .inbox-question-send").evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().height));
    assert(heights.every((height) => height >= 44), "Question buttons must provide a phone-sized touch target.");
    await page.screenshot({ path: path.join(output, `${width}-${answer}-pending.png`), fullPage: true });
    if (answer === "option") await page.locator(".inbox-question-option").first().click();
    else {
      await page.locator(".inbox-question-freeform textarea").fill("Use violet");
      await page.locator(".inbox-question-send").click();
    }
    await page.locator(".inbox-question-answer").waitFor();
    assert.match(await page.locator(".inbox-question-answer").textContent(), answer === "option" ? /Keep blue/ : /Use violet/);
    assert.equal(await page.locator(".inbox-question-option").count(), 0);
    const call = await page.evaluate(() => window.calls.find((entry) => entry.function === 'decision_requests.resolve'));
    assert.equal(call.payload.action, answer === "option" ? "blue" : "freeform");
    if (answer === "freeform") assert.equal(call.payload.note, "Use violet");
    await page.screenshot({ path: path.join(output, `${width}-${answer}-answered.png`), fullPage: true });
    captures.push({ width, answer, overflow, call });
    await page.close();
  }
  await writeFile(path.join(output, "measurements.json"), JSON.stringify({ head, data_source: "source fixtures", captures }, null, 2));
  process.stdout.write(`Verified ${captures.length} Inbox question cases at 1440 and 375 pixels.\n`);
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
