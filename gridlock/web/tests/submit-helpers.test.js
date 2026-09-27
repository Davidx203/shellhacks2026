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

test("buildCommitBody sends only the chosen rows plus the status the submitter saw and the upload reference", () => {
  const preview = {
    utility: "DESC", origin: "pdf", submitted_by: "Ana", upload_sha256: "a".repeat(64),
    rows: [
      { row: { project_id: "DESC_1" }, status: "new" },
      { row: { project_id: "DESC_2" }, status: "update" },
      { row: { project_id: "DESC_3" }, status: "unchanged" },
    ],
  };
  assert.deepStrictEqual(h.buildCommitBody(preview, [0, 1]), {
    utility: "DESC", origin: "pdf", submitted_by: "Ana",
    rows: [{ project_id: "DESC_1" }, { project_id: "DESC_2" }],
    expected: { DESC_1: "new", DESC_2: "update" }, upload_sha256: "a".repeat(64),
  });
});

test("buildCommitBody omits the upload reference for form submissions", () => {
  const preview = { utility: "GPC", origin: "form", rows: [{ row: { project_id: "GPC_SUB1" }, status: "new" }] };
  const body = h.buildCommitBody(preview, [0]);
  assert.strictEqual("upload_sha256" in body, false);
  assert.strictEqual(body.submitted_by, "");
});

test("entryLabel and entryEndpoints prefer the summary so partial updates show the real project", () => {
  const entry = {
    row: { project_id: "GPC_20277", project_name: "", endpoint_a: "", endpoint_b: "" },
    summary: { project_id: "GPC_20277", project_name: "McIntosh - Purrysburg", endpoint_a: "McIntosh", endpoint_b: "Purrysburg", in_service_date: "2026-06-01" },
  };
  assert.strictEqual(h.entryLabel(entry), "GPC_20277: McIntosh - Purrysburg");
  assert.strictEqual(h.entryEndpoints(entry), "McIntosh – Purrysburg");
  const plain = { row: { project_id: "P1", project_name: "N", endpoint_a: "A", endpoint_b: "" } };
  assert.strictEqual(h.entryLabel(plain), "P1: N");
  assert.strictEqual(h.entryEndpoints(plain), "A");
});
