const test = require("node:test");
const assert = require("node:assert");
const h = require("../submit-helpers.js");

test("buildFormPayload trims values, keeps only known fields and adds company and note", () => {
  const payload = h.buildFormPayload({ project_name: "  Okatie - Bluffton ", voltage_kv: " 115 ", junk: "x", lat_a: "" }, "GPC", " Ana ");
  assert.deepStrictEqual(payload, { utility: "GPC", submitted_by: "Ana", project_name: "Okatie - Bluffton", voltage_kv: "115" });
});

test("statusBadge labels every status and falls back safely", () => {
  assert.strictEqual(h.statusBadge("new").label, "New");
  assert.strictEqual(h.statusBadge("update").label, "Update");
  assert.strictEqual(h.statusBadge("unchanged").label, "Unchanged");
  assert.strictEqual(h.statusBadge("invalid").label, "Invalid");
  assert.strictEqual(h.statusBadge("weird").label, "weird");
});

test("describeChanges lists old to new per field", () => {
  assert.strictEqual(h.describeChanges({ in_service_date: ["2024-12-31", "2025-06-01"], voltage_kv: ["", "115"] }),
    "in_service_date: 2024-12-31 → 2025-06-01; voltage_kv: (empty) → 115");
  assert.strictEqual(h.describeChanges({}), "");
});

test("selectableIndexes returns only new or update rows without errors", () => {
  const entries = [
    { status: "new", errors: [] }, { status: "unchanged", errors: [] }, { status: "invalid", errors: ["x"] },
    { status: "update", errors: [] }, { status: "new", errors: ["x"] },
  ];
  assert.deepStrictEqual(h.selectableIndexes(entries), [0, 3]);
});

test("jobMessage and errorText produce readable text", () => {
  assert.match(h.jobMessage({ status: "running", message: "" }), /Updating/);
  assert.match(h.jobMessage({ status: "failed", message: "boom" }), /boom/);
  assert.strictEqual(h.jobMessage({ status: "done", message: "" }), "Done. Reloading the map…");
  assert.strictEqual(h.errorText({ detail: "Not a PDF" }), "Not a PDF");
  assert.strictEqual(h.errorText({ detail: { message: "Nothing to save.", skipped: [{ project_id: "GPC_1", reason: "unchanged" }] } }),
    "Nothing to save. GPC_1: unchanged");
  assert.strictEqual(h.errorText(null), "Something went wrong.");
});
