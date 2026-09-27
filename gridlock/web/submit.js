const submitState = { preview: null };

function submitEl(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  });
  [].concat(children).forEach((child) => node.append(child));
  return node;
}

function setSubmitStatus(message, isError = false) {
  const status = document.querySelector("#submit-status");
  status.textContent = message;
  status.classList.toggle("error", isError);
}

async function submitJson(url, options) {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {}
  if (!response.ok) throw new Error(errorText(payload));
  return payload;
}

function renderPreview(container, preview) {
  submitState.preview = preview;
  container.replaceChildren();
  const selectable = new Set(selectableIndexes(preview.rows));
  const table = submitEl("table", { class: "submit-table" }, [
    submitEl("tr", {}, ["", "Status", "Project", "Endpoints", "In service", "Details"].map((h) => submitEl("th", {}, h))),
  ]);
  preview.rows.forEach((entry, index) => {
    const badge = statusBadge(entry.status);
    const checkbox = submitEl("input", { type: "checkbox", "data-index": String(index) });
    checkbox.checked = selectable.has(index);
    checkbox.disabled = !selectable.has(index);
    const details = entry.errors.length
      ? submitEl("span", { class: "row-errors" }, entry.errors.join("; "))
      : document.createTextNode(describeChanges(entry.changes));
    table.append(submitEl("tr", {}, [
      submitEl("td", {}, checkbox),
      submitEl("td", {}, submitEl("span", { class: `badge ${badge.className}` }, badge.label)),
      submitEl("td", {}, `${entry.row.project_id}: ${entry.row.project_name}`),
      submitEl("td", {}, [entry.row.endpoint_a, entry.row.endpoint_b].filter(Boolean).join(" – ")),
      submitEl("td", {}, entry.row.in_service_date),
      submitEl("td", {}, details),
    ]));
  });
  container.append(table);
  if (selectable.size) {
    const confirm = submitEl("button", { type: "button", class: "primary" }, "Confirm and add to the map");
    confirm.addEventListener("click", () => commitPreview(container));
    container.append(confirm);
  } else {
    container.append(submitEl("p", {}, "Nothing here can be added. Fix the errors or change the file."));
  }
}

async function previewPdf() {
  const file = document.querySelector("#pdf-file").files[0];
  if (!file) return setSubmitStatus("Choose a PDF first.", true);
  const body = new FormData();
  body.append("utility", document.querySelector("#pdf-utility").value);
  body.append("file", file);
  setSubmitStatus("Reading the PDF…");
  try {
    const preview = await submitJson(`${API}/submissions/preview/pdf`, { method: "POST", body });
    renderPreview(document.querySelector("#pdf-result"), { ...preview, submitted_by: document.querySelector("#pdf-by").value });
    setSubmitStatus(`${preview.rows.length} project(s) found. Review and confirm.`);
  } catch (error) {
    document.querySelector("#pdf-result").replaceChildren();
    setSubmitStatus(error.message, true);
  }
}

async function previewForm(event) {
  event.preventDefault();
  const form = document.querySelector("#project-form");
  const values = Object.fromEntries(new FormData(form).entries());
  const payload = buildFormPayload(values, values.utility, values.submitted_by);
  setSubmitStatus("Checking…");
  try {
    const preview = await submitJson(`${API}/submissions/preview/form`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    renderPreview(document.querySelector("#form-result"), { ...preview, submitted_by: values.submitted_by });
    setSubmitStatus("Review and confirm.");
  } catch (error) {
    document.querySelector("#form-result").replaceChildren();
    setSubmitStatus(error.message, true);
  }
}

async function commitPreview(container) {
  const preview = submitState.preview;
  const chosen = [...container.querySelectorAll("input[type=checkbox]:checked")].map((box) => preview.rows[Number(box.dataset.index)].row);
  if (!chosen.length) return setSubmitStatus("Tick at least one row.", true);
  container.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const result = await submitJson(`${API}/submissions/commit`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ utility: preview.utility, origin: preview.origin, submitted_by: preview.submitted_by || "", rows: chosen }),
    });
    const skipped = result.skipped.length ? ` (${result.skipped.length} skipped)` : "";
    setSubmitStatus(`Saved ${result.saved.length} project(s)${skipped}. ${jobMessage({ status: "running" })}`);
    await pollJob(result.job_id);
  } catch (error) {
    container.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    setSubmitStatus(error.message, true);
  }
}

async function pollJob(jobId) {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const job = await submitJson(`${API}/submissions/jobs/${jobId}`);
    if (job.status === "done") {
      setSubmitStatus(jobMessage(job));
      setTimeout(() => window.location.reload(), 600);
      return;
    }
    if (job.status === "failed") {
      setSubmitStatus(jobMessage(job), true);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  setSubmitStatus("The update is taking longer than expected. Check History and try again.", true);
}

async function loadHistory() {
  const list = document.querySelector("#history-list");
  list.replaceChildren(submitEl("p", {}, "Loading…"));
  try {
    const rows = await submitJson(`${API}/submissions`);
    list.replaceChildren();
    if (!rows.length) return list.append(submitEl("p", {}, "No submissions yet."));
    const table = submitEl("table", { class: "submit-table" }, [
      submitEl("tr", {}, ["When", "Project", "By", "Status", ""].map((h) => submitEl("th", {}, h))),
    ]);
    rows.forEach((row) => {
      const rejected = row.status === "rejected";
      const button = submitEl("button", { type: "button" }, rejected ? "Restore" : "Reject");
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const result = await submitJson(`${API}/submissions/${row.submission_id}/${rejected ? "restore" : "reject"}`, { method: "POST" });
          setSubmitStatus(`${rejected ? "Restored" : "Rejected"}. ${jobMessage({ status: "running" })}`);
          await pollJob(result.job_id);
        } catch (error) {
          button.disabled = false;
          setSubmitStatus(error.message, true);
        }
      });
      table.append(submitEl("tr", {}, [
        submitEl("td", {}, row.submitted_at.slice(0, 16).replace("T", " ")),
        submitEl("td", {}, `${row.project_id}: ${row.project_name}`),
        submitEl("td", {}, `${row.submitted_by} (${row.origin})`),
        submitEl("td", {}, row.status),
        submitEl("td", {}, button),
      ]));
    });
    list.append(table);
  } catch (error) {
    list.replaceChildren();
    setSubmitStatus(error.message, true);
  }
}

function initSubmitDialog() {
  const dialog = document.querySelector("#submit-dialog");
  document.querySelector("#open-submit").addEventListener("click", () => { setSubmitStatus(""); dialog.showModal(); });
  document.querySelector("#close-submit").addEventListener("click", () => dialog.close());
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-tab]").forEach((other) => other.classList.toggle("active", other === tab));
      document.querySelectorAll("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== tab.dataset.tab; });
      setSubmitStatus("");
      if (tab.dataset.tab === "history") loadHistory();
    });
  });
  document.querySelector("#pdf-preview").addEventListener("click", previewPdf);
  document.querySelector("#project-form").addEventListener("submit", previewForm);
}

initSubmitDialog();
