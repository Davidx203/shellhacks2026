const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "main.js"), "utf8");

function load(name) {
  const match = source.match(new RegExp(`function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}\\n`));
  assert.ok(match, `main.js must define ${name}`);
  const context = { URLSearchParams };
  vm.createContext(context);
  vm.runInContext(match[0] + `\nthis.${name} = ${name};`, context);
  return context[name];
}

test("formatUsd renders whole dollars with commas, never a fraction", () => {
  const formatUsd = load("formatUsd");
  assert.strictEqual(formatUsd(606061), "$606,061");
  assert.strictEqual(formatUsd(0), "$0");
  assert.strictEqual(formatUsd(1234567.8), "$1,234,568");
  assert.strictEqual(formatUsd(null), "$0");
  assert.strictEqual(formatUsd(undefined), "$0");
  assert.strictEqual(formatUsd("not a number"), "$0");
});

test("costBriefQuery omits blank or invalid inputs and keeps valid ones", () => {
  const costBriefQuery = load("costBriefQuery");
  assert.strictEqual(costBriefQuery("", ""), "");
  assert.strictEqual(costBriefQuery("8", ""), "?shared_mi=8");
  assert.strictEqual(costBriefQuery("", "25000"), "?cost_per_acre=25000");
  assert.strictEqual(costBriefQuery("8", "25000"), "?shared_mi=8&cost_per_acre=25000");
  assert.strictEqual(costBriefQuery("abc", "-5"), "");        // non-numeric and negative are ignored
  assert.strictEqual(costBriefQuery("0", "0"), "");            // zero corridor/cost is not a usable override
});
