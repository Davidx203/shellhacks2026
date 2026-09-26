const API = "http://localhost:8000";
const map = L.map("map").setView([33.0, -81.5], 7);
const projectLayers = new Map();
const overlapLayers = new Map();
const opportunityCapLayers = new Map();
const opportunityCapPoints = new Map();
const allOverlaps = new Map();
const substationLayers = new Map();
const substationGroups = new Map();
const overlapGroup = L.layerGroup().addTo(map);
const opportunityCapGroup = L.layerGroup().addTo(map);
const substationGroup = L.layerGroup().addTo(map);
let selectedRadii = [];
let selectedFocus = [];
let selectedOverlapId = null;

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

map.on("click", () => clearSelectedOverlap());

const colors = {
  GPC: "#1c67d2",
  DESC: "#e36b2c",
};

function num(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function projectCenter(project) {
  const lat = num(project.lat_center);
  const lon = num(project.lon_center);
  return lat === null || lon === null ? null : [lat, lon];
}

function endpoints(project) {
  const a = [num(project.lat_a), num(project.lon_a)];
  const b = [num(project.lat_b), num(project.lon_b)];
  if (a[0] !== null && a[1] !== null && b[0] !== null && b[1] !== null) return [a, b];
  return null;
}

function confidenceStyle(project) {
  const base = {
    color: colors[project.utility] || "#555",
    fillColor: colors[project.utility] || "#555",
    weight: 4,
    opacity: 0.95,
    fillOpacity: 0.85,
  };
  if (project.confidence_tier === "medium") return { ...base, dashArray: "7 7" };
  if (project.confidence_tier === "low") return { ...base, fillOpacity: 0.05, opacity: 0.5 };
  return base;
}

function addProject(project) {
  const style = confidenceStyle(project);
  const pts = endpoints(project);
  const center = projectCenter(project);
  if (!center) return;

  const layers = [];
  if (pts) {
    layers.push(L.polyline(pts, style).addTo(map));
  }
  const layer = L.layerGroup(layers).addTo(map);

  layers.forEach((item) => item.bindPopup(`
    <strong>${project.project_name}</strong><br>
    ${project.utility} · ${project.voltage_kv || "?"} kV<br>
    In service: ${project.in_service_date || "unknown"}<br>
    Confidence: ${project.confidence_tier}<br>
    Source: ${project.source_ref || project.source_file || "fixture"}
  `));
  projectLayers.set(project.project_id, layer);
}

function coordinateKey(latlng) {
  return `${latlng[0].toFixed(6)},${latlng[1].toFixed(6)}`;
}

function milesBetween(a, b) {
  const radius = 3958.8;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLon = toRad(b[1] - a[1]);
  const lat1 = toRad(a[0]);
  const lat2 = toRad(b[0]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * radius * Math.asin(Math.sqrt(h));
}

function buildSubstationGroups(projects) {
  substationGroups.clear();
  projects.forEach((project) => {
    const pts = endpoints(project);
    const points = pts || [projectCenter(project)].filter(Boolean);
    points.forEach((point) => {
      let key = [...substationGroups.entries()].find(([, group]) => milesBetween(group.point, point) <= 0.1)?.[0];
      if (!key) key = coordinateKey(point);
      if (!substationGroups.has(key)) {
        substationGroups.set(key, { point, utilities: new Set(), projectIds: new Set(), names: [] });
      }
      const group = substationGroups.get(key);
      group.utilities.add(project.utility);
      group.projectIds.add(project.project_id);
      group.names.push(`${project.utility}: ${project.project_name}`);
    });
  });
}

function drawSubstations() {
  substationLayers.forEach((layer) => substationGroup.removeLayer(layer));
  substationLayers.clear();
  substationGroups.forEach((group, key) => {
    const layer = substationMarker(group).addTo(substationGroup);
    substationLayers.set(key, layer);
  });
}

function substationMarker(group) {
  const utilities = [...group.utilities];
  const isShared = utilities.length > 1;
  const primaryColor = colors[utilities[0]] || "#555";
  const secondaryColor = colors[utilities[1]] || primaryColor;
  const markerClass = isShared ? "substation-marker shared" : "substation-marker normal";

  const marker = L.marker(group.point, {
    icon: L.divIcon({
      className: "",
      html: `<div class="${markerClass}" style="--utility-color:${primaryColor}; --utility-color-2:${secondaryColor}"></div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    }),
    zIndexOffset: 450,
  });
  marker.bindPopup(`<strong>Substation / project location</strong><br>${group.names.join("<br>")}`);
  return marker;
}

function addOverlap(overlap) {
  const gpc = projectCenter(overlap.gpc);
  const desc = projectCenter(overlap.desc);
  if (!gpc || !desc) return;

  const layer = L.polyline([gpc, desc], {
    color: "#1f9d55",
    weight: 3 + Number(overlap.score || 0) * 3,
    opacity: 0.75,
  }).addTo(overlapGroup);
  setLinePulse(layer, true);

  layer.bindPopup(`
    <strong>#${overlap.rank} ${overlap.overlap_id}</strong><br>
    ${overlap.distance_mi} miles apart<br>
    Score: ${overlap.score}
  `);
  layer.on("click", (event) => {
    L.DomEvent.stopPropagation(event);
    selectOverlap(overlap);
  });
  overlapLayers.set(overlap.overlap_id, layer);

  const caps = L.layerGroup([
    opportunityCapForPoint(gpc, "G", colors.GPC),
    opportunityCapForPoint(desc, "D", colors.DESC),
  ]).addTo(opportunityCapGroup);
  opportunityCapLayers.set(overlap.overlap_id, caps);
  opportunityCapPoints.set(overlap.overlap_id, [gpc, desc]);
}

function renderList(overlaps) {
  const list = document.querySelector("#overlaps");
  list.innerHTML = "";
  overlaps.forEach((overlap) => {
    const li = document.createElement("li");
    li.dataset.overlapId = overlap.overlap_id;
    const button = document.createElement("button");
    button.innerHTML = `
      <div><span class="rank">#${overlap.rank}</span> ${overlap.overlap_id}</div>
      <div>${overlap.gpc.project_name}</div>
      <div>${overlap.desc.project_name}</div>
      <div class="meta">${overlap.distance_mi} mi · ${overlap.time_gap_days} days · score ${overlap.score}</div>
    `;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectOverlap(overlap);
    });
    li.appendChild(button);
    list.appendChild(li);
  });
}

function selectOverlap(overlap) {
  const gpc = projectCenter(overlap.gpc);
  const desc = projectCenter(overlap.desc);
  if (!gpc || !desc) return;
  selectedOverlapId = overlap.overlap_id;
  updateOverlapVisibility();
  updateProjectVisibility(overlap);
  updateListVisibility();
  selectedRadii.forEach((layer) => map.removeLayer(layer));
  selectedFocus.forEach((layer) => map.removeLayer(layer));
  selectedRadii = [
    L.circle(gpc, radiusStyle()).addTo(map),
    L.circle(desc, radiusStyle()).addTo(map),
  ];
  selectedFocus = [
    distanceLabel(gpc, desc, `${overlap.distance_mi} mi`),
  ];
  renderInspector(overlap);
  const bounds = L.latLngBounds([gpc, desc]).pad(0.4);
  map.flyToBounds(bounds);
}

function clearSelectedOverlap() {
  if (!selectedOverlapId) return;
  selectedOverlapId = null;
  selectedRadii.forEach((layer) => map.removeLayer(layer));
  selectedFocus.forEach((layer) => map.removeLayer(layer));
  selectedRadii = [];
  selectedFocus = [];
  projectLayers.forEach((layer) => {
    if (!map.hasLayer(layer)) layer.addTo(map);
  });
  substationLayers.forEach((layer) => {
    if (!substationGroup.hasLayer(layer)) layer.addTo(substationGroup);
  });
  overlapLayers.forEach((layer) => {
    layer.setStyle({ opacity: 0.75, weight: 3 });
    setLinePulse(layer, true);
    if (!overlapGroup.hasLayer(layer)) layer.addTo(overlapGroup);
  });
  opportunityCapLayers.forEach((layer) => {
    if (!opportunityCapGroup.hasLayer(layer)) layer.addTo(opportunityCapGroup);
  });
  applySubstationVisibility();
  document.querySelector("#inspector").innerHTML = `
    <h2>Selected opportunity</h2>
    <p>Click a ranked overlap to zoom in and show the 25 mile coordination radius.</p>
  `;
  updateListVisibility();
}

function updateOverlapVisibility() {
  overlapLayers.forEach((layer, id) => {
    if (id === selectedOverlapId) {
      layer.setStyle({ opacity: 0.95, weight: 7 });
      setLinePulse(layer, false);
      if (!overlapGroup.hasLayer(layer)) layer.addTo(overlapGroup);
    } else {
      setLinePulse(layer, false);
      overlapGroup.removeLayer(layer);
    }
  });
  opportunityCapLayers.forEach((layer, id) => {
    if (id === selectedOverlapId) {
      if (!opportunityCapGroup.hasLayer(layer)) layer.addTo(opportunityCapGroup);
    } else {
      opportunityCapGroup.removeLayer(layer);
    }
  });
}

function setLinePulse(layer, isPulsing) {
  const path = layer.getElement?.();
  if (path) path.classList.toggle("pulse-line", isPulsing);
}

function updateProjectVisibility(overlap) {
  const involved = new Set([overlap.project_id_gpc, overlap.project_id_desc]);
  projectLayers.forEach((layer, id) => {
    if (involved.has(id)) {
      if (!map.hasLayer(layer)) layer.addTo(map);
    } else {
      map.removeLayer(layer);
    }
  });
  applySubstationVisibility(involved);
}

function visibleOpportunityCapPoints() {
  const visible = [];
  opportunityCapPoints.forEach((points, id) => {
    if (!selectedOverlapId || id === selectedOverlapId) visible.push(...points);
  });
  return visible;
}

function applySubstationVisibility(involvedProjectIds = null) {
  const capPoints = visibleOpportunityCapPoints();
  substationLayers.forEach((layer, key) => {
    const group = substationGroups.get(key);
    const involved = !involvedProjectIds || [...group.projectIds].some((projectId) => involvedProjectIds.has(projectId));
    const coveredByCap = capPoints.some((point) => milesBetween(group.point, point) <= 0.12);
    if (involved && !coveredByCap) {
      if (!substationGroup.hasLayer(layer)) layer.addTo(substationGroup);
    } else {
      substationGroup.removeLayer(layer);
    }
  });
}

function nearbySubstationGroup(latlng) {
  return [...substationGroups.values()].find((group) => milesBetween(group.point, latlng) <= 0.12);
}

function updateListVisibility() {
  document.querySelectorAll("#overlaps li").forEach((item) => {
    const isSelected = selectedOverlapId && item.dataset.overlapId === selectedOverlapId;
    item.classList.toggle("is-hidden", Boolean(selectedOverlapId) && !isSelected);
    item.classList.toggle("is-selected", Boolean(isSelected));
  });
}

function opportunityCapForPoint(latlng, label, color, zIndexOffset = 650) {
  const group = nearbySubstationGroup(latlng);
  const utilities = group ? [...group.utilities] : [];
  if (utilities.length > 1) {
    return opportunityCap(latlng, label, colors.GPC, "shared", zIndexOffset, colors.DESC);
  }
  return opportunityCap(latlng, label, color, group ? "combined" : "plain", zIndexOffset);
}

function opportunityCap(latlng, label, color, variant, zIndexOffset = 650, secondColor = color) {
  const className = `opportunity-cap ${variant}`;
  return L.marker(latlng, {
    icon: L.divIcon({
      className: "",
      html: `<div class="${className}" style="--cap-color:${color}; --cap-color-2:${secondColor}">${label}</div>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    }),
    zIndexOffset,
  });
}

function distanceLabel(a, b, text) {
  const midpoint = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  return L.marker(midpoint, {
    icon: L.divIcon({
      className: "",
      html: `<div class="distance-label">${text} apart</div>`,
      iconSize: [90, 28],
      iconAnchor: [45, 36],
    }),
    zIndexOffset: 950,
  }).addTo(map);
}

function radiusStyle() {
  return {
    radius: 40234,
    color: "#1f9d55",
    weight: 2,
    opacity: 0.75,
    fillColor: "#1f9d55",
    fillOpacity: 0.08,
  };
}

function renderInspector(overlap) {
  document.querySelector("#inspector").innerHTML = `
    <h2>Selected opportunity</h2>
    <p><strong>#${overlap.rank} ${overlap.overlap_id}</strong> connects nearby project center points from GPC and DESC.</p>
    <div class="inspector-grid">
      <div class="metric"><span>Distance</span><b>${overlap.distance_mi} mi</b></div>
      <div class="metric"><span>Time gap</span><b>${overlap.time_gap_days} days</b></div>
      <div class="metric"><span>Score</span><b>${overlap.score}</b></div>
      <div class="metric"><span>Voltage</span><b>${overlap.voltage_match === "true" ? "match" : "differs"}</b></div>
    </div>
  `;
}

async function load() {
  const [projectsRes, overlapsRes] = await Promise.all([
    fetch(`${API}/projects`),
    fetch(`${API}/overlaps?limit=20`),
  ]);
  if (!projectsRes.ok || !overlapsRes.ok) throw new Error("API request failed");
  const projects = await projectsRes.json();
  const overlaps = await overlapsRes.json();
  buildSubstationGroups(projects);
  projects.forEach(addProject);
  drawSubstations();
  overlaps.forEach((overlap) => {
    allOverlaps.set(overlap.overlap_id, overlap);
    addOverlap(overlap);
  });
  applySubstationVisibility();
  renderList(overlaps);
  document.querySelector("#status").textContent = `${projects.length} projects and ${overlaps.length} overlaps loaded from the API.`;
}

load().catch((error) => {
  document.querySelector("#status").textContent = `Could not load API data: ${error.message}`;
});
