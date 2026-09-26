const map = L.map("map", {
  center: [25.7617, -80.1918],
  zoom: 12,
  zoomControl: true,
});

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

const state = {
  tool: "select",
  color: "#e94f37",
  draft: [],
  draftLayer: null,
  annotations: [],
  selectedId: null,
  freehand: false,
};

const els = {
  tools: document.querySelectorAll(".tool"),
  color: document.querySelector("#color"),
  label: document.querySelector("#label"),
  finish: document.querySelector("#finish-shape"),
  undo: document.querySelector("#undo-point"),
  deleteSelected: document.querySelector("#delete-selected"),
  clearAll: document.querySelector("#clear-all"),
  list: document.querySelector("#annotation-list"),
  count: document.querySelector("#count"),
  hint: document.querySelector("#hint"),
  search: document.querySelector("#search"),
  searchBtn: document.querySelector("#search-btn"),
};

const hints = {
  select: "Drag to pan. Click an annotation to select it.",
  point: "Click the map to drop a labeled location point.",
  line: "Click each route point. Use Finish Shape when done.",
  polygon: "Click around the area. Use Finish Shape to close it.",
  circle: "Click the center, then click the outside edge for radius.",
  freehand: "Hold and drag on the map to sketch.",
};

function setTool(tool) {
  state.tool = tool;
  state.draft = [];
  clearDraft();
  map.dragging[tool === "freehand" ? "disable" : "enable"]();
  els.tools.forEach((btn) => btn.classList.toggle("active", btn.dataset.tool === tool));
  els.hint.textContent = hints[tool];
}

function layerStyle(color = state.color) {
  return {
    color,
    fillColor: color,
    fillOpacity: 0.22,
    opacity: 0.95,
    weight: 4,
  };
}

function nextName(type) {
  const custom = els.label.value.trim();
  return custom || `${type[0].toUpperCase()}${type.slice(1)} ${state.annotations.length + 1}`;
}

function addAnnotation(type, layer, color, name) {
  const id = crypto.randomUUID();
  layer._annotationId = id;
  layer.on("click", (event) => {
    L.DomEvent.stopPropagation(event);
    selectAnnotation(id);
  });
  layer.bindPopup(`<strong>${escapeHtml(name)}</strong><br>${type}`);
  state.annotations.push({ id, type, name, color, layer });
  selectAnnotation(id);
  renderList();
}

function selectAnnotation(id) {
  state.selectedId = id;
  state.annotations.forEach((item) => {
    if (item.layer.setStyle) {
      item.layer.setStyle({
        ...layerStyle(item.color),
        weight: item.id === id ? 7 : 4,
      });
    }
  });
  renderList();
}

function renderList() {
  els.count.textContent = state.annotations.length;
  els.list.innerHTML = "";
  state.annotations.forEach((item) => {
    const li = document.createElement("li");
    li.className = item.id === state.selectedId ? "selected" : "";
    li.innerHTML = `
      <span class="swatch" style="background:${item.color}"></span>
      <span class="annotation-name">${escapeHtml(item.name)} · ${item.type}</span>
    `;
    li.addEventListener("click", () => {
      selectAnnotation(item.id);
      const bounds = item.layer.getBounds ? item.layer.getBounds() : null;
      if (bounds && bounds.isValid()) map.fitBounds(bounds.pad(0.25));
      if (item.layer.getLatLng) map.panTo(item.layer.getLatLng());
    });
    els.list.appendChild(li);
  });
}

function redrawDraft() {
  clearDraft();
  if (!state.draft.length) return;
  if (state.tool === "line" || state.tool === "freehand") {
    state.draftLayer = L.polyline(state.draft, layerStyle()).addTo(map);
  }
  if (state.tool === "polygon") {
    state.draftLayer = L.polygon(state.draft, layerStyle()).addTo(map);
  }
  if (state.tool === "circle" && state.draft.length === 2) {
    const radius = state.draft[0].distanceTo(state.draft[1]);
    state.draftLayer = L.circle(state.draft[0], { ...layerStyle(), radius }).addTo(map);
  }
}

function clearDraft() {
  if (state.draftLayer) {
    map.removeLayer(state.draftLayer);
    state.draftLayer = null;
  }
}

function finishShape() {
  const type = state.tool;
  const color = state.color;
  const name = nextName(type);
  let layer = null;

  if (type === "line" && state.draft.length >= 2) {
    layer = L.polyline(state.draft, layerStyle(color)).addTo(map);
  }
  if (type === "polygon" && state.draft.length >= 3) {
    layer = L.polygon(state.draft, layerStyle(color)).addTo(map);
  }
  if (type === "circle" && state.draft.length >= 2) {
    layer = L.circle(state.draft[0], {
      ...layerStyle(color),
      radius: state.draft[0].distanceTo(state.draft[1]),
    }).addTo(map);
  }
  if (type === "freehand" && state.draft.length >= 2) {
    layer = L.polyline(state.draft, layerStyle(color)).addTo(map);
  }

  if (!layer) {
    els.hint.textContent = "Add enough points before finishing this shape.";
    return;
  }

  addAnnotation(type, layer, color, name);
  state.draft = [];
  clearDraft();
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char];
  });
}

function dropPoint(latlng) {
  const color = state.color;
  const name = nextName("point");
  const marker = L.circleMarker(latlng, {
    radius: 9,
    color: "#ffffff",
    weight: 3,
    fillColor: color,
    fillOpacity: 1,
  }).addTo(map);
  addAnnotation("point", marker, color, name);
}

map.on("click", (event) => {
  if (state.tool === "select") {
    state.selectedId = null;
    renderList();
    return;
  }
  if (state.tool === "point") {
    dropPoint(event.latlng);
    return;
  }
  if (["line", "polygon", "circle"].includes(state.tool)) {
    if (state.tool === "circle" && state.draft.length === 2) state.draft = [];
    state.draft.push(event.latlng);
    redrawDraft();
    if (state.tool === "circle" && state.draft.length === 2) finishShape();
  }
});

map.on("mousedown", (event) => {
  if (state.tool !== "freehand") return;
  state.freehand = true;
  state.draft = [event.latlng];
  redrawDraft();
});

map.on("mousemove", (event) => {
  if (!state.freehand) return;
  state.draft.push(event.latlng);
  redrawDraft();
});

map.on("mouseup", () => {
  if (!state.freehand) return;
  state.freehand = false;
  finishShape();
});

els.tools.forEach((btn) => btn.addEventListener("click", () => setTool(btn.dataset.tool)));
els.color.addEventListener("input", (event) => {
  state.color = event.target.value;
  redrawDraft();
});
els.finish.addEventListener("click", finishShape);
els.undo.addEventListener("click", () => {
  state.draft.pop();
  redrawDraft();
});
els.deleteSelected.addEventListener("click", () => {
  const index = state.annotations.findIndex((item) => item.id === state.selectedId);
  if (index < 0) return;
  map.removeLayer(state.annotations[index].layer);
  state.annotations.splice(index, 1);
  state.selectedId = null;
  renderList();
});
els.clearAll.addEventListener("click", () => {
  state.annotations.forEach((item) => map.removeLayer(item.layer));
  state.annotations = [];
  state.selectedId = null;
  state.draft = [];
  clearDraft();
  renderList();
});

async function searchPlace() {
  const q = els.search.value.trim();
  if (!q) return;
  els.hint.textContent = "Searching...";
  const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(q)}&limit=1`;
  try {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    const [place] = await res.json();
    if (!place) {
      els.hint.textContent = "No matching place found.";
      return;
    }
    map.setView([Number(place.lat), Number(place.lon)], 14);
    els.hint.textContent = `Centered on ${place.display_name.split(",")[0]}.`;
  } catch {
    els.hint.textContent = "Search is unavailable right now.";
  }
}

els.searchBtn.addEventListener("click", searchPlace);
els.search.addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchPlace();
});

setTool("select");
