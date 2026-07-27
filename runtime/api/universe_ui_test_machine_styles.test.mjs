import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Test Mac callout borders remain theme-relative", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/test_machine.css",
    import.meta.url,
  ), "utf8");
  for (const token of ["--yoke-good", "--yoke-warn", "--yoke-crit"]) {
    assert.equal(
      css.includes(
        `color-mix(in srgb, var(${token}) 45%, var(--yoke-border))`,
      ),
      true,
    );
  }
  assert.doesNotMatch(
    css,
    /color-mix\\(in srgb, var\\(--yoke-(?:good|warn|crit)\\) 45%, white\\)/,
  );
});

test("Test Mac layout keeps the shared prototype geometry", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/test_machine.css",
    import.meta.url,
  ), "utf8");
  const supportCss = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/test_machine_support.css",
    import.meta.url,
  ), "utf8");

  assert.match(
    css,
    /\.test-machine-head \{[^}]*gap: 14px;[^}]*margin-bottom: 20px;/,
  );
  assert.match(
    css,
    /\.test-machine-head h1 \{[^}]*font-size: 20px;/,
  );
  assert.match(
    css,
    /\.test-machine-columns \{[^}]*grid-template-columns: minmax\(0, 1\.55fr\) minmax\(260px, \.75fr\);[^}]*gap: 14px;[^}]*align-items: start;/,
  );
  assert.match(
    css,
    /\.test-machine-lease-bar \{[^}]*height: 5px;[^}]*flex: 1;/,
  );
  assert.match(
    css,
    /\.test-machine-lease-bar > i \{[^}]*width: 58%;[^}]*height: 100%;/,
  );
  assert.match(
    css,
    /\.test-machine-stat \{[^}]*padding: 10px 11px;/,
  );
  assert.match(
    css,
    /\.test-machine-stat \.mh \{[^}]*letter-spacing: \.06em;/,
  );
  assert.match(
    css,
    /\.test-machine-stat \.mv \{[^}]*font-size: 12\.5px;/,
  );
  assert.match(
    css,
    /\.test-machine-method \{[^}]*gap: 9px;[^}]*padding: 9px 11px;[^}]*border: 1px solid var\(--yoke-border\);/,
  );
  assert.match(
    css,
    /\.test-machine-method-icon \{[^}]*width: 30px;[^}]*height: 30px;/,
  );
  assert.match(
    css,
    /\.test-machine-dialog-secrets > p \+\s+\.test-machine-command \{[^}]*margin-top: 9px;/,
  );
  assert.match(
    supportCss,
    /\.test-machine-command-identity \{[^}]*display: flex;[^}]*align-items: center;[^}]*gap: 8px;/,
  );
});

test("Test Mac settings footer stacks and stretches at phone width", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/test_machine.css",
    import.meta.url,
  ), "utf8");

  assert.match(
    css,
    /@media \(max-width: 780px\) \{[\s\S]*?\.test-machine-dialog-footer \{[^}]*align-items: stretch;[^}]*flex-direction: column;/,
  );
  assert.match(
    css,
    /@media \(max-width: 780px\) \{[\s\S]*?\.test-machine-dialog-footer > p \{[^}]*min-width: 0;/,
  );
  assert.doesNotMatch(
    css,
    /\.test-machine-dialog-footer \{[^}]*grid-template-columns:/,
  );
});
