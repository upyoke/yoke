import { defineConfig } from "@playwright/test";
import { existsSync } from "fs";
import { resolve } from "path";

const remoteURL = process.env.BASE_URL;
const venvPython = resolve(__dirname, "../../.venv/bin/python3");
const python = existsSync(venvPython) ? venvPython : "python3";

export default defineConfig({
  testDir: ".",
  testIgnore: ["smoke.spec.ts"],
  outputDir: "../test-results",
  reporter: [["list"], ["html", { outputFolder: "../playwright-report", open: "never" }]],
  timeout: 30_000,
  retries: 1,
  use: {
    baseURL: remoteURL || "http://localhost:{{web_port}}",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
  ...(remoteURL
    ? {}
    : {
        webServer: [
          {
            command: "npm run dev",
            port: {{web_port}},
            reuseExistingServer: true,
            timeout: 30_000,
          },
          {
            command: `${python} -m uvicorn api.main:app --host 0.0.0.0 --port {{api_port}}`,
            url: "http://localhost:{{api_port}}/api/health",
            cwd: "../..",
            reuseExistingServer: true,
            timeout: 30_000,
          },
        ],
      }),
});
