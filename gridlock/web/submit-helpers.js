const FORM_FIELDS = [
  "utility_project_id", "project_name", "endpoint_a", "endpoint_b", "voltage_kv", "length_mi",
  "est_cost_usd", "build_start", "in_service_date", "lat_a", "lon_a", "lat_b", "lon_b",
];

function buildFormPayload(values, utility, submittedBy) {
  const payload = { utility, submitted_by: String(submittedBy || "").trim() };
  FORM_FIELDS.forEach((field) => {
    const value = String(values[field] ?? "").trim();
    if (value) payload[field] = value;
  });
  return payload;
}

function statusBadge(status) {
  const known = {
    new: { label: "New", className: "badge-new" },
    update: { label: "Update", className: "badge-update" },
    unchanged: { label: "Unchanged", className: "badge-muted" },
    invalid: { label: "Invalid", className: "badge-invalid" },
  };
  return known[status] || { label: String(status), className: "badge-muted" };
}

function describeChanges(changes) {
  return Object.entries(changes || {})
    .map(([field, [oldValue, newValue]]) => `${field}: ${oldValue || "(empty)"} → ${newValue || "(empty)"}`)
    .join("; ");
}

function selectableIndexes(entries) {
  return entries.flatMap((entry, index) =>
    (entry.status === "new" || entry.status === "update") && !(entry.errors || []).length ? [index] : []);
}

function buildCommitBody(preview, indexes) {
  const chosen = indexes.map((index) => preview.rows[index]);
  const body = {
    utility: preview.utility,
    origin: preview.origin,
    submitted_by: preview.submitted_by || "",
    rows: chosen.map((entry) => entry.row),
    expected: Object.fromEntries(chosen.map((entry) => [entry.row.project_id, entry.status])),
  };
  if (preview.origin === "pdf" && preview.upload_sha256) body.upload_sha256 = preview.upload_sha256;
  return body;
}

function entryLabel(entry) {
  const shown = entry.summary || entry.row;
  return `${shown.project_id}: ${shown.project_name}`;
}

function entryEndpoints(entry) {
  const shown = entry.summary || entry.row;
  return [shown.endpoint_a, shown.endpoint_b].filter(Boolean).join(" \u2013 ");
}

function jobMessage(job) {
  if (job.status === "failed") return `The update failed: ${job.message || "unknown error"}. Your submission is saved; you can retry.`;
  if (job.status === "done") return "Done. Reloading the map…";
  return "Updating the map data (about 10 seconds)…";
}

function errorText(payload) {
  if (!payload || payload.detail === undefined) return "Something went wrong.";
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  const skipped = (detail.skipped || []).map((s) => `${s.project_id}: ${s.reason}`).join("; ");
  return [detail.message, skipped].filter(Boolean).join(" ");
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { FORM_FIELDS, buildFormPayload, statusBadge, describeChanges, selectableIndexes, buildCommitBody, entryLabel, entryEndpoints, jobMessage, errorText };
}
