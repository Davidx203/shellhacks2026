const API = "http://localhost:8000";

const signedInCompany = GridlockAuth.current();
document.querySelector("#signed-in-company").textContent = signedInCompany.name;
document.querySelector("#sign-out").addEventListener("click", () => {
  GridlockAuth.signOut();
  window.location.replace("./index.html");
});

const colors = {
  GPC: "#1d6ed5",
  DESC: "#e36d2f",
  overlap: "#179653",
};

let map;
let projects = [];
let overlaps = [];
let selectedOverlapId = null;
let distanceMarker = null;
let flyByTimer = null;
let suppressMapClick = false;
let currentCameraIndex = 1;
let listFilters = {
  search: "",
  maxDistance: null,
  minScore: null,
  voltageOnly: false,
  topOnly: false,
};
const TOP_N = 20;

const substationGroups = new Map();
const substationMarkers = new Map();
const opportunityCaps = new Map();
const opportunityCapPoints = new Map();
const overlapsById = new Map();
let costBriefRequestId = 0;
const routesByProject = new Map();

const emptyFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

const cameraStops = ["gpc", "center", "desc"];

const defaultView = { center: [-81.5, 33.0], zoom: 7, pitch: 45, bearing: -8 };

const basemaps = {
  satellite: "mapbox://styles/mapbox/satellite-streets-v12",
  streets: "mapbox://styles/mapbox/streets-v12",
};
let currentBasemap = "satellite";
let dataLoaded = false;
let layerEventsBound = false;

function getMapboxToken() {
  const params = new URLSearchParams(window.location.search);
  const queryToken = params.get("mapbox_token") || params.get("token");
  if (queryToken) {
    localStorage.setItem("mapboxToken", queryToken.trim());
    return queryToken.trim();
  }

  const stored = localStorage.getItem("mapboxToken");
  if (stored) return stored;

  const pasted = window.prompt("Paste your Mapbox public token. It starts with pk.");
  if (pasted?.trim()) {
    localStorage.setItem("mapboxToken", pasted.trim());
    return pasted.trim();
  }
  return "";
}

function initMap() {
  const token = getMapboxToken();
  if (!token) {
    setStatus("Mapbox token required. Add ?token=pk.your_token to the URL or set localStorage.mapboxToken.");
    return;
  }

  mapboxgl.accessToken = token;
  map = new mapboxgl.Map({
    container: "map",
    style: basemaps[currentBasemap],
    ...defaultView,
    antialias: true,
  });

  map.addControl(new mapboxgl.NavigationControl({ showZoom: false, visualizePitch: true }), "top-left");
  map.addControl(new mapboxgl.FullscreenControl(), "top-left");

  map.on("load", async () => {
    addTerrain();
    await load();
  });
  map.on("style.load", restoreLayersAfterStyleChange);
  initZoomSlider();
  document.querySelector("#reset-view").addEventListener("click", resetView);

  map.on("click", () => {
    if (suppressMapClick) return;
    clearSelectedOverlap();
  });
}

function initZoomSlider() {
  const slider = document.querySelector("#zoom-slider");
  let dragging = false;
  slider.value = map.getZoom();
  slider.addEventListener("pointerdown", () => {
    dragging = true;
  });
  window.addEventListener("pointerup", () => {
    dragging = false;
    slider.value = map.getZoom();
  });
  slider.addEventListener("input", () => {
    map.stop();
    map.setZoom(Number(slider.value));
  });
  map.on("zoom", () => {
    if (!dragging) slider.value = map.getZoom();
  });
}

function resetView() {
  if (flyByTimer) {
    clearTimeout(flyByTimer);
    flyByTimer = null;
  }
  document.querySelectorAll(".mapboxgl-popup").forEach((popup) => popup.remove());
  clearSelectedOverlap();
  endFlyby();
  map.flyTo({ ...defaultView, duration: 1100, essential: true });
}

function initBasemapControls() {
  const buttons = document.querySelectorAll("[data-basemap]");
  try {
    const saved = localStorage.getItem("basemap");
    if (saved in basemaps) currentBasemap = saved;
  } catch {}
  buttons.forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      setBasemap(button.dataset.basemap);
    });
  });
  markActiveBasemap();
}

function markActiveBasemap() {
  document.querySelectorAll("[data-basemap]").forEach((button) => {
    button.classList.toggle("active", button.dataset.basemap === currentBasemap);
  });
}

function setBasemap(name) {
  if (!(name in basemaps) || name === currentBasemap) return;
  currentBasemap = name;
  try {
    localStorage.setItem("basemap", name);
  } catch {}
  markActiveBasemap();
  if (map) map.setStyle(basemaps[name]);
}

function restoreLayersAfterStyleChange() {
  if (!dataLoaded || map.getSource("project-lines")) return;
  addTerrain();
  addMapSourcesAndLayers();
  const selected = selectedOverlapId ? overlapsById.get(selectedOverlapId) : null;
  if (selected) updateSelectionCircles([projectCenter(selected.gpc), projectCenter(selected.desc)]);
  updateOverlapVisibility();
  updateProjectVisibility(selected || null);
}

function addTerrain() {
  if (!map.getSource("mapbox-dem")) {
    map.addSource("mapbox-dem", {
      type: "raster-dem",
      url: "mapbox://mapbox.mapbox-terrain-dem-v1",
      tileSize: 512,
      maxzoom: 14,
    });
  }
  map.setTerrain({ source: "mapbox-dem", exaggeration: 1.35 });
}

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

function lngLat(point) {
  return [point[1], point[0]];
}

function coordinateKey(point) {
  return `${point[0].toFixed(6)},${point[1].toFixed(6)}`;
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

function bearingBetween(a, b) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const toDeg = (rad) => (rad * 180) / Math.PI;
  const lat1 = toRad(a[0]);
  const lat2 = toRad(b[0]);
  const dLon = toRad(b[1] - a[1]);
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return toDeg(Math.atan2(y, x));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function namesHtml(group) {
  return group.names.map(escapeHtml).join("<br>");
}

function formatUsd(amount) {
  const number = Number(amount);
  return `$${Number.isFinite(number) ? Math.round(number).toLocaleString("en-US") : 0}`;
}

function costBriefQuery(sharedMi, costPerAcre) {
  const params = new URLSearchParams();
  const mi = Number(sharedMi);
  const cost = Number(costPerAcre);
  if (sharedMi !== "" && Number.isFinite(mi) && mi > 0) params.set("shared_mi", String(mi));
  if (costPerAcre !== "" && Number.isFinite(cost) && cost > 0) params.set("cost_per_acre", String(cost));
  const query = params.toString();
  return query ? `?${query}` : "";
}

function setStatus(message) {
  document.querySelector("#status").textContent = message;
}

function initCameraControls() {
  document.querySelector("#view-prev").addEventListener("click", (event) => {
    event.stopPropagation();
    stepCamera(-1);
  });
  document.querySelector("#view-next").addEventListener("click", (event) => {
    event.stopPropagation();
    stepCamera(1);
  });
  document.querySelectorAll("[data-camera-view]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      setCameraView(button.dataset.cameraView);
    });
  });
  setCameraControlsEnabled(false);
}

function initListFilters() {
  const search = document.querySelector("#filter-search");
  const distance = document.querySelector("#filter-distance");
  const score = document.querySelector("#filter-score");
  const voltage = document.querySelector("#filter-voltage");

  function updateFilters() {
    listFilters = {
      search: search.value.trim().toLowerCase(),
      maxDistance: distance.value ? Number(distance.value) : null,
      minScore: score.value ? Number(score.value) : null,
      voltageOnly: voltage.checked,
      topOnly: listFilters.topOnly,
    };
    renderFilteredList();
  }

  document.querySelectorAll("[data-top]").forEach((button) => {
    button.addEventListener("click", () => {
      listFilters.topOnly = button.dataset.top === "20";
      document.querySelectorAll("[data-top]").forEach((other) => {
        other.classList.toggle("active", other === button);
      });
      updateFilters();
    });
  });

  [search, distance, score, voltage].forEach((control) => {
    control.addEventListener("input", updateFilters);
    control.addEventListener("change", updateFilters);
  });
}

function buildSubstationGroups() {
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

function projectLineFeatures() {
  return projects.flatMap((project) => {
    const pts = endpoints(project);
    if (!pts) return [];
    const route = routesByProject.get(project.project_id);
    return [
      {
        type: "Feature",
        properties: {
          route_mi: route ? route.route_mi : "",
          origin: project.origin || "report",
          project_id: project.project_id,
          project_name: project.project_name,
          utility: project.utility,
          voltage_kv: project.voltage_kv || "?",
          in_service_date: project.in_service_date || "unknown",
          confidence_tier: project.confidence_tier || "unknown",
          source_ref: project.source_ref || project.source_file || "fixture",
        },
        geometry: {
          type: "LineString",
          coordinates: route ? route.coordinates : pts.map(lngLat),
        },
      },
    ];
  });
}

const TOUCH_MI = 0.05;

function closestPoints(overlap) {
  const values = [overlap.lat_gpc, overlap.lon_gpc, overlap.lat_desc, overlap.lon_desc].map(num);
  if (values.every((value) => value !== null)) return { gpc: [values[0], values[1]], desc: [values[2], values[3]] };
  return { gpc: projectCenter(overlap.gpc), desc: projectCenter(overlap.desc) };
}

function isTouching(overlap) {
  return Number(overlap.distance_mi) <= TOUCH_MI;
}

function overlapLineFeatures() {
  return overlaps.flatMap((overlap) => {
    const { gpc, desc } = closestPoints(overlap);
    if (!gpc || !desc || isTouching(overlap)) return [];
    return [
      {
        type: "Feature",
        properties: {
          overlap_id: overlap.overlap_id,
          rank: overlap.rank,
          score: Number(overlap.score || 0),
          distance_mi: overlap.distance_mi,
        },
        geometry: {
          type: "LineString",
          coordinates: [lngLat(gpc), lngLat(desc)],
        },
      },
    ];
  });
}

function addMapSourcesAndLayers() {
  map.addSource("selection-circles", {
    type: "geojson",
    data: emptyFeatureCollection,
  });
  map.addLayer({
    id: "selection-circle-fill",
    type: "fill",
    source: "selection-circles",
    paint: {
      "fill-color": colors.overlap,
      "fill-opacity": 0.1,
    },
  });
  map.addLayer({
    id: "selection-circle-line",
    type: "line",
    source: "selection-circles",
    paint: {
      "line-color": colors.overlap,
      "line-width": 2,
      "line-opacity": 0.78,
    },
  });

  map.addSource("project-lines", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: projectLineFeatures(),
    },
  });
  map.addLayer({
    id: "project-lines",
    type: "line",
    source: "project-lines",
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": ["match", ["get", "utility"], "GPC", colors.GPC, "DESC", colors.DESC, "#596973"],
      "line-width": 4,
      "line-opacity": 0.94,
    },
  });

  map.addLayer({
    id: "project-lines-submitted",
    type: "line",
    source: "project-lines",
    filter: ["!=", ["get", "origin"], "report"],
    layout: { "line-cap": "butt", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 2, "line-dasharray": [1.5, 1.5], "line-opacity": 0.95 },
  });

  map.addSource("overlap-lines", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: overlapLineFeatures(),
    },
  });
  map.addLayer({
    id: "overlap-lines",
    type: "line",
    source: "overlap-lines",
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": colors.overlap,
      "line-width": 6,
      "line-opacity": 0.74,
    },
  });

  if (!layerEventsBound) {
    layerEventsBound = true;
    bindMapLayerEvents();
    requestAnimationFrame(animateOverlapLines);
  }
}

function bindMapLayerEvents() {
  map.on("click", "overlap-lines", (event) => {
    suppressNextMapClick();
    const id = event.features?.[0]?.properties?.overlap_id;
    const overlap = overlapsById.get(id);
    if (overlap) selectOverlap(overlap);
  });
  map.on("mouseenter", "overlap-lines", () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", "overlap-lines", () => {
    map.getCanvas().style.cursor = "";
  });

  map.on("click", "project-lines", (event) => {
    suppressNextMapClick();
    const props = event.features?.[0]?.properties;
    if (!props) return;
    const routeNote = props.route_mi ? `Route along power line: ${escapeHtml(props.route_mi)} mi<br>` : "";
    const submittedNote = props.origin && props.origin !== "report" ? "<em>Submitted by the company \u00b7 unverified</em><br>" : "";
    new mapboxgl.Popup({ closeButton: true })
      .setLngLat(event.lngLat)
      .setHTML(`
        <strong>${escapeHtml(props.project_name)}</strong><br>
        ${escapeHtml(props.utility)} · ${escapeHtml(props.voltage_kv)} kV<br>
        In service: ${escapeHtml(props.in_service_date)}<br>
        Confidence: ${escapeHtml(props.confidence_tier)}<br>
        ${routeNote}
        ${submittedNote}
        Source: ${escapeHtml(props.source_ref)}
      `)
      .addTo(map);
  });
  map.on("mouseenter", "project-lines", () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", "project-lines", () => {
    map.getCanvas().style.cursor = "";
  });
}

function suppressNextMapClick() {
  suppressMapClick = true;
  setTimeout(() => {
    suppressMapClick = false;
  }, 0);
}

function animateOverlapLines(time = 0) {
  if (map?.getLayer("overlap-lines")) {
    if (selectedOverlapId) {
      map.setPaintProperty("overlap-lines", "line-width", 7);
      map.setPaintProperty("overlap-lines", "line-opacity", 0.95);
    } else {
      const pulse = (Math.sin(time / 220) + 1) / 2;
      map.setPaintProperty("overlap-lines", "line-width", 5 + pulse * 5);
      map.setPaintProperty("overlap-lines", "line-opacity", 0.52 + pulse * 0.38);
    }
  }
  requestAnimationFrame(animateOverlapLines);
}

function drawSubstations() {
  substationMarkers.forEach((marker) => marker.remove());
  substationMarkers.clear();

  substationGroups.forEach((group, key) => {
    const marker = new mapboxgl.Marker({ element: substationElement(group), anchor: "center" })
      .setLngLat(lngLat(group.point))
      .setPopup(new mapboxgl.Popup().setHTML(`<strong>Substation / project location</strong><br>${namesHtml(group)}`))
      .addTo(map);
    substationMarkers.set(key, marker);
  });
}

function substationElement(group) {
  const utilities = [...group.utilities];
  const isShared = utilities.length > 1;
  const el = document.createElement("div");
  el.className = isShared ? "substation-marker shared" : "substation-marker normal";
  el.style.setProperty("--utility-color", colors[utilities[0]] || "#596973");
  el.style.setProperty("--utility-color-2", colors[utilities[1]] || colors[utilities[0]] || "#596973");
  return el;
}

function drawOpportunityCaps() {
  opportunityCaps.forEach((markers) => markers.forEach((marker) => marker.remove()));
  opportunityCaps.clear();
  opportunityCapPoints.clear();

  overlaps.forEach((overlap) => {
    const { gpc, desc } = closestPoints(overlap);
    if (!gpc || !desc) return;
    if (isTouching(overlap)) {
      opportunityCaps.set(overlap.overlap_id, [opportunityCapForPoint(gpc, "×", colors.overlap, overlap)]);
      opportunityCapPoints.set(overlap.overlap_id, [gpc]);
      return;
    }
    const markers = [
      opportunityCapForPoint(gpc, "G", colors.GPC, overlap),
      opportunityCapForPoint(desc, "D", colors.DESC, overlap),
    ];
    opportunityCaps.set(overlap.overlap_id, markers);
    opportunityCapPoints.set(overlap.overlap_id, [gpc, desc]);
  });
}

function nearbySubstationGroup(point) {
  return [...substationGroups.values()].find((group) => milesBetween(group.point, point) <= 0.12);
}

function opportunityCapForPoint(point, label, color, overlap) {
  const group = nearbySubstationGroup(point);
  const utilities = group ? [...group.utilities] : [];
  let variant = group ? "combined" : "plain";
  let secondColor = color;
  if (utilities.length > 1) {
    variant = "shared";
    secondColor = colors.DESC;
    color = colors.GPC;
  }

  const el = document.createElement("div");
  el.className = `opportunity-cap ${variant}`;
  el.textContent = label;
  el.style.setProperty("--cap-color", color);
  el.style.setProperty("--cap-color-2", secondColor);
  el.addEventListener("click", (event) => {
    event.stopPropagation();
    suppressNextMapClick();
    selectOverlap(overlap);
  });
  return new mapboxgl.Marker({ element: el, anchor: "center" }).setLngLat(lngLat(point)).addTo(map);
}

const bandLabels = {
  crossing: "Crossing",
  share_land: "Share land",
  share_logistics: "Share logistics",
  share_crews: "Share crews",
};

function windowText(overlap) {
  if (String(overlap.windows_overlap).toLowerCase() === "true") return `windows overlap ${overlap.overlap_days} d`;
  return overlap.window_gap_days ? `${overlap.window_gap_days} d gap` : "timing unknown";
}

function renderList(items) {
  const list = document.querySelector("#overlaps");
  list.innerHTML = "";
  items.forEach((overlap) => {
    const li = document.createElement("li");
    li.dataset.overlapId = overlap.overlap_id;
    const button = document.createElement("button");
    button.innerHTML = `
      <div><span class="rank">#${escapeHtml(overlap.rank)}</span> ${escapeHtml(overlap.overlap_id)}</div>
      <div>${escapeHtml(overlap.gpc.project_name)}</div>
      <div>${escapeHtml(overlap.desc.project_name)}</div>
      <div class="meta">${escapeHtml(overlap.distance_mi)} mi · ${escapeHtml(bandLabels[overlap.band] || "n/a")} · ${escapeHtml(windowText(overlap))} · score ${escapeHtml(overlap.score)}</div>
    `;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectOverlap(overlap);
    });
    li.appendChild(button);
    list.appendChild(li);
  });
}

function filteredOverlaps() {
  return overlaps.filter((overlap) => {
    if (listFilters.topOnly && Number(overlap.rank) > TOP_N) return false;
    if (listFilters.maxDistance !== null && Number(overlap.distance_mi) > listFilters.maxDistance) return false;
    if (listFilters.minScore !== null && Number(overlap.score) < listFilters.minScore) return false;
    if (listFilters.voltageOnly && String(overlap.voltage_match).toLowerCase() !== "true") return false;
    if (listFilters.search) {
      const haystack = [
        overlap.overlap_id,
        overlap.gpc?.project_name,
        overlap.desc?.project_name,
        overlap.gpc?.project_id,
        overlap.desc?.project_id,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(listFilters.search)) return false;
    }
    return true;
  });
}

function filtersActive() {
  return Boolean(
    listFilters.search ||
      listFilters.maxDistance !== null ||
      listFilters.minScore !== null ||
      listFilters.voltageOnly ||
      listFilters.topOnly,
  );
}

function shownOverlapIds() {
  return filtersActive() ? new Set(filteredOverlaps().map((overlap) => overlap.overlap_id)) : null;
}

function overlapIsShown(id) {
  const shown = shownOverlapIds();
  return !shown || shown.has(id);
}

function shownProjectIds() {
  const ids = new Set();
  filteredOverlaps().forEach((overlap) => {
    ids.add(overlap.project_id_gpc);
    ids.add(overlap.project_id_desc);
  });
  return ids;
}

function matchFilter(property, values) {
  return values.length ? ["match", ["get", property], values, true, false] : ["==", ["get", property], "__none__"];
}

function applyFiltersToMap() {
  if (!map || !map.getLayer("overlap-lines")) return;
  if (selectedOverlapId && !overlapIsShown(selectedOverlapId)) clearSelectedOverlap();
  updateOverlapVisibility();
  const selected = selectedOverlapId ? overlapsById.get(selectedOverlapId) : null;
  updateProjectVisibility(selected || null);
}

function renderFilteredList() {
  const items = filteredOverlaps();
  renderList(items);
  document.querySelector("#filter-count").textContent = `${items.length} shown`;
  updateListVisibility();
  applyFiltersToMap();
}

function selectOverlap(overlap) {
  const { gpc, desc } = closestPoints(overlap);
  if (!gpc || !desc) return;

  selectedOverlapId = overlap.overlap_id;
  updateOverlapVisibility();
  updateProjectVisibility(overlap);
  updateListVisibility();
  updateSelectionCircles([gpc, desc]);
  updateDistanceLabel(gpc, desc, isTouching(overlap) ? "touching" : `${overlap.distance_mi} mi`);
  renderInspector(overlap);
  renderCostBrief(overlap);
  setCameraControlsEnabled(true);
  setCameraView("center");
}

function clearSelectedOverlap() {
  if (!selectedOverlapId) return;
  endFlyby();
  selectedOverlapId = null;
  updateOverlapVisibility();
  updateProjectVisibility(null);
  updateListVisibility();
  updateSelectionCircles([]);
  removeDistanceLabel();
  setCameraControlsEnabled(false);
  document.querySelector("#inspector").innerHTML = `
    <h2>Selected opportunity</h2>
    <p>Click a ranked overlap to zoom in and show the 25 mile coordination radius.</p>
  `;
  costBriefRequestId += 1;
  document.querySelector("#cost-brief").hidden = true;
  document.querySelector("#cost-shared-mi").value = "";
  document.querySelector("#cost-per-acre").value = "";
  document.querySelector("#cost-narrative").textContent = "";
  document.querySelector("#cost-result").innerHTML = "";
  document.querySelector("#cost-assumptions").textContent = "";
}

function stepCamera(direction) {
  if (!selectedOverlapId) return;
  currentCameraIndex = (currentCameraIndex + direction + cameraStops.length) % cameraStops.length;
  setCameraView(cameraStops[currentCameraIndex]);
}

function setCameraView(view) {
  const overlap = overlapsById.get(selectedOverlapId);
  if (!overlap) return;
  const { gpc, desc } = closestPoints(overlap);
  if (!gpc || !desc) return;

  currentCameraIndex = Math.max(0, cameraStops.indexOf(view));
  setActiveCameraButton(view);
  if (view === "gpc") {
    flyToSite(gpc, desc, -18);
    return;
  }
  if (view === "desc") {
    flyToSite(desc, gpc, 18);
    return;
  }
  const context = isTouching(overlap) ? [projectCenter(overlap.gpc), projectCenter(overlap.desc)].filter(Boolean) : [];
  flyToOpportunity(gpc, desc, context);
}

function setCameraControlsEnabled(isEnabled) {
  const controls = document.querySelector("#camera-controls");
  controls.classList.toggle("is-disabled", !isEnabled);
  controls.querySelectorAll("button").forEach((button) => {
    button.disabled = !isEnabled;
  });
  if (!isEnabled) {
    currentCameraIndex = 1;
    setActiveCameraButton("center");
  }
}

function setActiveCameraButton(view) {
  document.querySelectorAll("[data-camera-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.cameraView === view);
  });
}

function updateOverlapVisibility() {
  if (!map.getLayer("overlap-lines")) return;
  const shown = shownOverlapIds();
  let lineFilter = null;
  if (selectedOverlapId) lineFilter = ["==", ["get", "overlap_id"], selectedOverlapId];
  else if (shown) lineFilter = matchFilter("overlap_id", [...shown]);
  map.setFilter("overlap-lines", lineFilter);
  opportunityCaps.forEach((markers, id) => {
    const visible = selectedOverlapId ? id === selectedOverlapId : !shown || shown.has(id);
    markers.forEach((marker) => {
      marker.getElement().style.display = visible ? "grid" : "none";
    });
  });
}

function setProjectFilter(filter) {
  map.setFilter("project-lines", filter);
  if (map.getLayer("project-lines-submitted")) {
    const submitted = ["!=", ["get", "origin"], "report"];
    map.setFilter("project-lines-submitted", filter ? ["all", submitted, filter] : submitted);
  }
}

function updateProjectVisibility(overlap) {
  if (!map.getLayer("project-lines")) return;
  if (!overlap) {
    if (filtersActive()) {
      const ids = shownProjectIds();
      setProjectFilter(matchFilter("project_id", [...ids]));
      applySubstationVisibility(ids);
    } else {
      setProjectFilter(null);
      applySubstationVisibility();
    }
    return;
  }
  const ids = [overlap.project_id_gpc, overlap.project_id_desc];
  setProjectFilter(["match", ["get", "project_id"], ids, true, false]);
  applySubstationVisibility(new Set(ids));
}

function visibleOpportunityCapPoints() {
  const visible = [];
  const shown = shownOverlapIds();
  opportunityCapPoints.forEach((points, id) => {
    if (selectedOverlapId ? id === selectedOverlapId : !shown || shown.has(id)) visible.push(...points);
  });
  return visible;
}

function applySubstationVisibility(involvedProjectIds = null) {
  const capPoints = visibleOpportunityCapPoints();
  substationMarkers.forEach((marker, key) => {
    const group = substationGroups.get(key);
    const involved = !involvedProjectIds || [...group.projectIds].some((projectId) => involvedProjectIds.has(projectId));
    const coveredByCap = capPoints.some((point) => milesBetween(group.point, point) <= 0.12);
    marker.getElement().style.display = involved && !coveredByCap ? "block" : "none";
  });
}

function updateListVisibility() {
  document.querySelectorAll("#overlaps li").forEach((item) => {
    const isSelected = selectedOverlapId && item.dataset.overlapId === selectedOverlapId;
    item.classList.toggle("is-hidden", Boolean(selectedOverlapId) && !isSelected);
    item.classList.toggle("is-selected", Boolean(isSelected));
  });
}

function updateSelectionCircles(points) {
  const source = map.getSource("selection-circles");
  if (!source) return;
  source.setData({
    type: "FeatureCollection",
    features: points.map((point) => circleFeature(point, 25)),
  });
}

function circleFeature(center, radiusMiles, steps = 96) {
  const coordinates = [];
  const distanceRadians = radiusMiles / 3958.8;
  const lat1 = (center[0] * Math.PI) / 180;
  const lon1 = (center[1] * Math.PI) / 180;

  for (let i = 0; i <= steps; i += 1) {
    const bearing = (i / steps) * Math.PI * 2;
    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(distanceRadians) +
        Math.cos(lat1) * Math.sin(distanceRadians) * Math.cos(bearing)
    );
    const lon2 =
      lon1 +
      Math.atan2(
        Math.sin(bearing) * Math.sin(distanceRadians) * Math.cos(lat1),
        Math.cos(distanceRadians) - Math.sin(lat1) * Math.sin(lat2)
      );
    coordinates.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }

  return {
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [coordinates],
    },
  };
}

function updateDistanceLabel(a, b, text) {
  removeDistanceLabel();
  const midpoint = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const el = document.createElement("div");
  el.className = "distance-label";
  el.textContent = text === "touching" ? "touching" : `${text} apart`;
  distanceMarker = new mapboxgl.Marker({ element: el, anchor: "bottom" }).setLngLat(lngLat(midpoint)).addTo(map);
}

function removeDistanceLabel() {
  if (distanceMarker) {
    distanceMarker.remove();
    distanceMarker = null;
  }
}

function flyToOpportunity(gpc, desc, context = []) {
  endFlyby();
  if (flyByTimer) clearTimeout(flyByTimer);
  const bounds = new mapboxgl.LngLatBounds(lngLat(gpc), lngLat(gpc));
  bounds.extend(lngLat(desc));
  context.forEach((point) => bounds.extend(lngLat(point)));
  const center = bounds.getCenter();
  const camera = map.cameraForBounds(bounds, {
    padding: { top: 130, bottom: 120, left: 430, right: 120 },
    maxZoom: 15.4,
  });
  const finalBearing = bearingBetween(gpc, desc) - 25;
  map.getContainer().classList.add("flyby-active");
  map.flyTo({
    center,
    zoom: Math.max(8, (camera?.zoom || 13) - 3.4),
    pitch: 38,
    bearing: finalBearing - 35,
    duration: 850,
    essential: true,
  });
  flyByTimer = setTimeout(() => {
    map.flyTo({
      center: camera?.center || center,
      zoom: camera?.zoom || 14.2,
      pitch: 62,
      bearing: finalBearing,
      duration: 1800,
      essential: true,
    });
    flyByTimer = setTimeout(() => {
      flyByTimer = null;
      endFlyby();
    }, 1850);
  }, 620);
}

function flyToSite(site, other, bearingOffset) {
  endFlyby();
  if (flyByTimer) clearTimeout(flyByTimer);
  const bearing = bearingBetween(site, other) + bearingOffset;
  map.getContainer().classList.add("flyby-active");
  map.flyTo({
    center: lngLat(site),
    zoom: 15.8,
    pitch: 64,
    bearing,
    duration: 1450,
    essential: true,
  });
  flyByTimer = setTimeout(() => {
    flyByTimer = null;
    endFlyby();
  }, 1500);
}

function endFlyby() {
  map?.getContainer().classList.remove("flyby-active");
}

function renderInspector(overlap) {
  document.querySelector("#inspector").innerHTML = `
    <h2>Selected opportunity</h2>
    <p><strong>#${escapeHtml(overlap.rank)} ${escapeHtml(overlap.overlap_id)}</strong> links the closest points of two nearby GPC and DESC projects.</p>
    <div class="inspector-grid">
      <div class="metric"><span>Closest distance</span><b>${escapeHtml(overlap.distance_mi)} mi</b></div>
      <div class="metric"><span>Coordination</span><b>${escapeHtml(bandLabels[overlap.band] || "n/a")}</b></div>
      <div class="metric"><span>Build windows</span><b>${escapeHtml(windowText(overlap))}</b></div>
      <div class="metric"><span>Score</span><b>${escapeHtml(overlap.score)}</b></div>
      <div class="metric"><span>Voltage</span><b>${String(overlap.voltage_match).toLowerCase() === "true" ? "match" : "differs"}</b></div>
    </div>
  `;
}

async function renderCostBrief(overlap) {
  const section = document.querySelector("#cost-brief");
  const narrativeEl = document.querySelector("#cost-narrative");
  const resultEl = document.querySelector("#cost-result");
  const assumptionsEl = document.querySelector("#cost-assumptions");
  section.hidden = false;
  narrativeEl.textContent = "Estimating shared right-of-way savings\u2026";
  resultEl.innerHTML = "";
  assumptionsEl.textContent = "";

  const requestId = ++costBriefRequestId;
  const query = costBriefQuery(
    document.querySelector("#cost-shared-mi").value,
    document.querySelector("#cost-per-acre").value,
  );
  let brief;
  try {
    const [briefRes, narrativeRes] = await Promise.all([
      fetch(`${API}/briefs/${overlap.overlap_id}${query}`),
      fetch(`${API}/briefs/${overlap.overlap_id}/narrative${query}`, { method: "POST" }),
    ]);
    if (!briefRes.ok) throw new Error("brief request failed");
    brief = await briefRes.json();
    const narrative = narrativeRes.ok ? (await narrativeRes.json()).narrative : "";
    if (requestId !== costBriefRequestId) return;
    narrativeEl.textContent = narrative || "Estimate unavailable for this opportunity.";
  } catch {
    if (requestId !== costBriefRequestId) return;
    narrativeEl.textContent = "Could not load a cost estimate for this opportunity.";
    return;
  }
  if (requestId !== costBriefRequestId) return;
  resultEl.innerHTML = `
    <div class="metric"><span>Shared corridor</span><b>${escapeHtml(brief.shared_corridor_mi)} mi</b></div>
    <div class="metric"><span>Est. land savings</span><b>${escapeHtml(formatUsd(brief.est_land_savings_usd))}</b></div>
    <div class="metric"><span>Right-of-way width</span><b>${escapeHtml(brief.row_width_ft)} ft</b></div>
    <div class="metric"><span>Shared land</span><b>${escapeHtml(brief.shared_acres)} acres</b></div>
  `;
  assumptionsEl.textContent = brief.assumptions_note || "";
}

function initCostInputs() {
  ["#cost-shared-mi", "#cost-per-acre"].forEach((selector) => {
    document.querySelector(selector).addEventListener("change", () => {
      const overlap = selectedOverlapId ? overlapsById.get(selectedOverlapId) : null;
      if (overlap) renderCostBrief(overlap);
    });
  });
}

async function load() {
  setStatus("Loading fixture data...");
  const [projectsRes, overlapsRes] = await Promise.all([
    fetch(`${API}/projects`),
    fetch(`${API}/overlaps?limit=200`),
  ]);
  if (!projectsRes.ok || !overlapsRes.ok) throw new Error("API request failed");
  projects = await projectsRes.json();
  overlaps = await overlapsRes.json();
  routesByProject.clear();
  try {
    const routesRes = await fetch(`${API}/routes`);
    if (routesRes.ok) {
      (await routesRes.json()).features.forEach((feature) => {
        routesByProject.set(feature.properties.project_id, {
          route_mi: feature.properties.route_mi,
          coordinates: feature.geometry.coordinates,
        });
      });
    }
  } catch {}
  overlaps.forEach((overlap) => overlapsById.set(overlap.overlap_id, overlap));

  buildSubstationGroups();
  addMapSourcesAndLayers();
  drawSubstations();
  drawOpportunityCaps();
  applySubstationVisibility();
  renderFilteredList();
  dataLoaded = true;
  setStatus(`${projects.length} projects and ${overlaps.length} overlaps loaded from the API.`);
}

initListFilters();
initCameraControls();
initBasemapControls();
initCostInputs();
initMap();
