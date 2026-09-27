const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "main.js"), "utf8");

function loadEscape() {
  const match = source.match(/function escapeHtml\([^)]*\) \{[\s\S]*?\n\}\n/);
  assert.ok(match, "main.js must define escapeHtml");
  const context = {};
  vm.createContext(context);
  vm.runInContext(match[0] + "\nthis.escapeHtml = escapeHtml;", context);
  return context.escapeHtml;
}

test("escapeHtml neutralises markup, quotes and non-strings", () => {
  const escapeHtml = loadEscape();
  assert.strictEqual(escapeHtml("<img src=x onerror=alert(1)>"), "&lt;img src=x onerror=alert(1)&gt;");
  assert.strictEqual(escapeHtml(`a "b" 'c' & d`), "a &quot;b&quot; &#39;c&#39; &amp; d");
  assert.strictEqual(escapeHtml(null), "");
  assert.strictEqual(escapeHtml(undefined), "");
  assert.strictEqual(escapeHtml(42), "42");
});

test("every HTML sink in main.js escapes project-controlled text", () => {
  const sinks = [...source.matchAll(/(?:setHTML\(|innerHTML\s*=\s*)`([\s\S]*?)`/g)].map((m) => m[1]);
  assert.ok(sinks.length >= 4, `expected to find the HTML sinks, found ${sinks.length}`);
  const risky = /project_name|source_ref|\.names|props\.|utility|overlap_id|origin/;
  const offenders = [];
  for (const template of sinks) {
    for (const expression of [...template.matchAll(/\$\{([^}]*)\}/g)].map((m) => m[1].trim())) {
      if (risky.test(expression) && !expression.startsWith("escapeHtml(")) offenders.push(expression);
    }
  }
  assert.deepStrictEqual(offenders, []);
});
