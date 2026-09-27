const params = new URLSearchParams(window.location.search);
const requestedApi = params.get("api");
if (requestedApi) localStorage.setItem("gridlockApi", requestedApi);

const API = (requestedApi || localStorage.getItem("gridlockApi") || "http://localhost:8000").replace(/\/$/, "");
const CURRENT_YEAR = new Date().getFullYear();
const MAX_DISTANCE_MI = 25;
const TIME_WINDOW_DAYS = 1825;
const COORDINATION_SCORE = 0.35;
const SLIDE_EXIT_MS = 540;
const SLIDE_ENTER_MS = 760;
const THEME_CLASSES = [
  "theme-aqua",
  "theme-amber",
  "theme-violet",
  "theme-blue",
  "theme-rose",
  "theme-mint",
  "theme-gold",
  "theme-cyan",
  "theme-magenta",
  "theme-white",
];

const UTILITY_LABELS = {
  GPC: "Georgia Power",
  DESC: "Dominion Energy SC",
};

const TYPE_LABELS = {
  new_line: "New Line",
  rebuild: "Rebuild",
  reconductor: "Reconductor",
  substation: "Substation",
  relay: "Relay",
  other: "Other",
};

const state = {
  projects: [],
  overlaps: [],
  selectedUtility: null,
  selectedYear: null,
  model: null,
  slides: [],
  slideIndex: 0,
  isTransitioning: false,
};

const app = document.querySelector("#app");

init();

async function init() {
  window.addEventListener("keydown", handleStoryKeys);
  try {
    await loadData();
    renderUtilityPicker();
  } catch (error) {
    renderError(error);
  }
}

async function loadData() {
  const [projects, overlaps] = await Promise.all([
    fetchJson(`${API}/projects`),
    fetchJson(`${API}/overlaps?limit=200`).catch(() => []),
  ]);
  state.projects = projects;
  state.overlaps = overlaps;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function renderError(error) {
  document.body.classList.remove("story-active");
  app.innerHTML = `
    <div class="error-state">
      <div>
        <p class="kicker">Grid Wrapped</p>
        <h1>Could not load grid data.</h1>
        <p class="lead">Start the FastAPI server at ${escapeHtml(API)}, then refresh this page.</p>
        <p class="lead empty-note">${escapeHtml(error.message || error)}</p>
      </div>
    </div>
  `;
}

function renderUtilityPicker() {
  document.body.classList.remove("story-active");
  const utilities = utilitySummaries();
  state.selectedUtility = null;
  state.selectedYear = null;
  state.model = null;
  state.slides = [];
  state.slideIndex = 0;
  state.isTransitioning = false;

  app.innerHTML = `
    <section class="picker-view">
      <div class="picker-header">
        <p class="kicker">Grid Wrapped</p>
        <h1>Choose a Utility</h1>
        <p class="lead">Whose future grid do you want to explore?</p>
      </div>
      <div class="picker-tools">
        <label class="search-wrap">
          <span aria-hidden="true">/</span>
          <input id="utility-search" type="search" placeholder="Search utilities..." autocomplete="off" />
        </label>
        <span class="count-pill">${utilities.length} utilities</span>
      </div>
      <div id="utility-list" class="utility-list"></div>
    </section>
  `;

  const search = document.querySelector("#utility-search");
  const list = document.querySelector("#utility-list");

  function drawUtilities() {
    const query = search.value.trim().toLowerCase();
    const matches = utilities.filter((utility) => {
      const haystack = `${utility.utility} ${utility.label}`.toLowerCase();
      return haystack.includes(query);
    });

    list.innerHTML = matches.length
      ? matches.map(utilityCard).join("")
      : `<p class="empty-note">No utilities match that search.</p>`;
  }

  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-utility]");
    if (!button) return;
    state.selectedUtility = button.dataset.utility;
    renderYearPicker();
  });
  search.addEventListener("input", drawUtilities);
  drawUtilities();
}

function utilityCard(summary) {
  const years = summary.years.length ? `${summary.years[0]}-${summary.years[summary.years.length - 1]}` : "no dated projects";
  const miles = summary.knownMiles > 0 ? ` · ${formatNumber(summary.knownMiles, 1)} known mi` : "";
  return `
    <button class="utility-card" type="button" data-utility="${escapeHtml(summary.utility)}">
      <div class="utility-top">
        <span class="utility-name">${escapeHtml(summary.label)}</span>
        <span class="count-pill">${escapeHtml(summary.utility)}</span>
      </div>
      <p class="utility-meta">${summary.projectCount} planned projects${miles}<br>${years}</p>
    </button>
  `;
}

function renderYearPicker() {
  document.body.classList.remove("story-active");
  state.isTransitioning = false;
  const utility = state.selectedUtility;
  const label = formatUtility(utility);
  const years = availableYearsForUtility(utility);
  state.selectedYear = years.includes(state.selectedYear) ? state.selectedYear : years[0];

  app.innerHTML = `
    <section class="picker-view">
      <div class="picker-header">
        <p class="kicker">${escapeHtml(label)}</p>
        <h1>Choose a Year</h1>
        <p class="lead">See ${escapeHtml(label)}'s future grid in review.</p>
      </div>
      <div id="year-grid" class="year-grid"></div>
      <div class="picker-footer">
        <button id="change-utility" class="secondary-button" type="button">Change Utility</button>
        <button id="generate-wrapped" class="primary-button" type="button">Generate My Wrapped -&gt;</button>
      </div>
    </section>
  `;

  const grid = document.querySelector("#year-grid");

  function drawYears() {
    grid.innerHTML = years.map((year) => yearCard(utility, year, year === state.selectedYear)).join("");
  }

  grid.addEventListener("click", (event) => {
    const button = event.target.closest("[data-year]");
    if (!button) return;
    state.selectedYear = Number(button.dataset.year);
    drawYears();
  });
  document.querySelector("#change-utility").addEventListener("click", renderUtilityPicker);
  document.querySelector("#generate-wrapped").addEventListener("click", () => {
    state.model = buildWrappedViewModel(state.selectedUtility, state.selectedYear, state.projects, state.overlaps);
    state.slides = buildSlides(state.model);
    state.slideIndex = 0;
    state.isTransitioning = false;
    renderStory();
  });
  drawYears();
}

function yearCard(utility, year, isSelected) {
  const yearProjects = projectsForUtilityYear(utility, year);
  const miles = sumKnownMiles(yearProjects);
  const details = [
    `${yearProjects.length} projects`,
    miles > 0 ? `${formatNumber(miles, 1)} known mi` : null,
  ].filter(Boolean).join(" · ");

  return `
    <button class="year-card ${isSelected ? "is-selected" : ""}" type="button" data-year="${year}">
      <span class="year-number">${year}</span>
      <span class="year-meta">${escapeHtml(details)}</span>
    </button>
  `;
}

function renderStory() {
  document.body.classList.add("story-active");
  const model = state.model;
  app.innerHTML = `
    <section class="story-view">
      <div id="progress-bar" class="progress-bar" aria-hidden="true"></div>
      <article id="story-panel" class="story-panel"></article>
      <div class="story-actions">
        <button id="story-prev" class="secondary-button" type="button">Back</button>
        <span id="slide-count" class="slide-count"></span>
        <button id="story-next" class="primary-button" type="button">Next</button>
      </div>
    </section>
  `;

  document.querySelector("#story-prev").addEventListener("click", previousSlide);
  document.querySelector("#story-next").addEventListener("click", nextSlide);
  state.isTransitioning = true;
  renderCurrentSlide("next", true);
}

function renderCurrentSlide(direction = "next", unlockAfterEntry = false) {
  const slide = state.slides[state.slideIndex];
  const panel = document.querySelector("#story-panel");
  const progress = document.querySelector("#progress-bar");
  const prev = document.querySelector("#story-prev");
  const next = document.querySelector("#story-next");
  const count = document.querySelector("#slide-count");
  const story = document.querySelector(".story-view");

  story?.classList.remove(...THEME_CLASSES);
  story?.classList.add(`theme-${slide.theme}`);

  panel.innerHTML = `
    <div class="slide is-entering enter-${direction} motion-${escapeHtml(slide.motion)} theme-${escapeHtml(slide.theme)}">
      <div class="background-word" aria-hidden="true">${escapeHtml(slide.backgroundWord)}</div>
      <div class="slide-topline">
        <span>${escapeHtml(state.model.utilityLabel)} / ${state.model.year}</span>
        <span>${escapeHtml(slide.kicker)}</span>
      </div>
      <h2>${escapeHtml(slide.title)}</h2>
      ${slide.body()}
    </div>
  `;

  progress.innerHTML = state.slides.map((_, index) => `
    <span class="progress-segment ${index < state.slideIndex ? "is-done" : ""} ${index === state.slideIndex ? "is-current" : ""}">
      <span></span>
    </span>
  `).join("");

  prev.disabled = state.slideIndex === 0;
  next.textContent = state.slideIndex === state.slides.length - 1 ? "Start Over" : "Next";
  count.textContent = `${state.slideIndex + 1} / ${state.slides.length}`;
  bindSlideActions();
  animateCounters(panel);
  setStoryControlsLocked(state.isTransitioning);

  if (unlockAfterEntry) {
    window.setTimeout(() => {
      state.isTransitioning = false;
      setStoryControlsLocked(false);
    }, SLIDE_ENTER_MS);
  }
}

function previousSlide() {
  if (state.slideIndex === 0) return;
  transitionToSlide(state.slideIndex - 1, "prev");
}

function nextSlide() {
  if (state.slideIndex === state.slides.length - 1) {
    exitStory(renderUtilityPicker);
    return;
  }
  transitionToSlide(state.slideIndex + 1, "next");
}

function transitionToSlide(targetIndex, direction) {
  if (state.isTransitioning) return;
  if (targetIndex < 0 || targetIndex >= state.slides.length) return;

  state.isTransitioning = true;
  setStoryControlsLocked(true);
  const panel = document.querySelector("#story-panel");
  const current = panel?.querySelector(".slide");
  current?.classList.remove("is-entering", "enter-next", "enter-prev");
  current?.classList.add(direction === "next" ? "is-leaving-left" : "is-leaving-right");

  window.setTimeout(() => {
    state.slideIndex = targetIndex;
    renderCurrentSlide(direction, true);
  }, SLIDE_EXIT_MS);
}

function exitStory(renderNextView) {
  if (state.isTransitioning) return;

  state.isTransitioning = true;
  setStoryControlsLocked(true);
  const current = document.querySelector("#story-panel .slide");
  current?.classList.remove("is-entering", "enter-next", "enter-prev");
  current?.classList.add("is-leaving-left");

  window.setTimeout(() => {
    renderNextView();
  }, SLIDE_EXIT_MS);
}

function setStoryControlsLocked(isLocked) {
  const story = document.querySelector(".story-view");
  if (!story) return;

  story.classList.toggle("is-transitioning", isLocked);
  const prev = document.querySelector("#story-prev");
  const next = document.querySelector("#story-next");
  const change = document.querySelector("#story-change");

  if (prev) prev.disabled = isLocked || state.slideIndex === 0;
  if (next) next.disabled = isLocked;
  if (change) change.disabled = isLocked;
}

function handleStoryKeys(event) {
  if (!document.querySelector(".story-view")) return;
  if (event.target.matches("input, textarea, button")) return;
  if (state.isTransitioning) return;
  if (event.key === "ArrowRight") nextSlide();
  if (event.key === "ArrowLeft") previousSlide();
}

function bindSlideActions() {
  const shareButton = document.querySelector("#share-wrapped");
  if (!shareButton) return;
  shareButton.addEventListener("click", shareWrapped);
}

async function shareWrapped() {
  const model = state.model;
  const summary = `${model.utilityLabel} ${model.year} Grid Wrapped: ${model.totalProjects} projects, ${formatNumber(model.totalTransmissionMileage, 1)} known miles, ${model.majorProjectCount} major projects, grid type ${model.gridPersonality.type}.`;
  const note = document.querySelector("#share-note");

  try {
    if (navigator.share) {
      await navigator.share({ title: "Grid Wrapped", text: summary });
      note.textContent = "Shared.";
      return;
    }
    await navigator.clipboard.writeText(summary);
    note.textContent = "Summary copied.";
  } catch {
    note.textContent = "Share canceled.";
  }
}

function buildWrappedViewModel(selectedUtility, selectedYear, allProjects, existingOverlaps) {
  const utilityProjects = allProjects.filter((project) => project.utility === selectedUtility);
  const utilityYearProjects = utilityProjects.filter((project) => projectAppliesToYear(project, selectedYear));
  const candidates = buildCrossUtilityCandidates(utilityYearProjects, allProjects, selectedUtility);
  const dominantProjectType = dominantType(utilityYearProjects);
  const biggestEra = findBiggestEra(selectedUtility, utilityProjects);
  const topCollaboration = findTopCollaboration(candidates);
  const missedConnections = findMissedConnections(candidates);
  const nearestOther = findNearestOther(utilityYearProjects, allProjects, selectedUtility);
  const hotspot = findHotspot(utilityYearProjects, allProjects, selectedUtility);
  const topProject = findTopProject(utilityYearProjects, candidates);
  const surpriseInsight = findSurpriseInsight(candidates, nearestOther);
  const totalTransmissionMileage = sumKnownMiles(utilityYearProjects);
  const majorProjectCount = countMajorProjects(utilityYearProjects);
  const potentialCollaborations = candidates.filter((candidate) => candidate.score >= COORDINATION_SCORE).length;
  const gridPersonality = chooseGridPersonality({
    utilityYearProjects,
    dominantProjectType,
    potentialCollaborations,
    spreadMiles: projectSpreadMiles(utilityYearProjects),
  });

  return {
    utility: selectedUtility,
    utilityLabel: formatUtility(selectedUtility),
    year: selectedYear,
    utilityProjects,
    utilityYearProjects,
    existingOverlaps,
    totalProjects: utilityYearProjects.length,
    totalTransmissionMileage,
    majorProjectCount,
    dominantProjectType,
    biggestEra,
    topCollaboration,
    missedConnections,
    nearestOther,
    hotspot,
    topProject,
    surpriseInsight,
    potentialCollaborations,
    gridPersonality,
  };
}

function buildSlides(model) {
  const missedSlide = model.missedConnections.length ? missedConnectionsSlide(model) : closestNeighborSlide(model);
  const slides = [
    futureGridSlide(model),
    favoriteThingSlide(model),
    biggestEraSlide(model),
    collaborationSlide(model),
    missedSlide,
    hotspotSlide(model),
    topProjectSlide(model),
    surpriseSlide(model),
    personalitySlide(model),
    shareSlide(model),
  ];
  const treatments = [
    ["surge", "FUTURE", "aqua"],
    ["pop", "BUILD", "amber"],
    ["rise", "ERA", "violet"],
    ["connect", "LINK", "blue"],
    ["drift", missedSlide.backgroundWord || "NEAR", "rose"],
    ["map", "HOTSPOT", "mint"],
    ["spotlight", "TOP", "gold"],
    ["reveal", "FOUND", "cyan"],
    ["stamp", "TYPE", "magenta"],
    ["settle", "SHARE", "white"],
  ];

  return slides.map((slide, index) => ({
    ...slide,
    motion: treatments[index][0],
    backgroundWord: slide.backgroundWord || treatments[index][1],
    theme: treatments[index][2],
  }));
}

function futureGridSlide(model) {
  return {
    kicker: "Your Future Grid",
    title: `Your ${model.year} Grid`,
    body: () => `
      <p class="slide-copy">${escapeHtml(model.utilityLabel)} has ${model.totalProjects} project${plural(model.totalProjects)} active or due in ${model.year}.</p>
      <div class="stats-grid">
        ${statTile(model.totalProjects, "planned projects")}
        ${statTile(formatNumber(model.totalTransmissionMileage, 1), "known line miles")}
        ${statTile(model.majorProjectCount, "major projects")}
      </div>
    `,
  };
}

function favoriteThingSlide(model) {
  const type = model.dominantProjectType;
  return {
    kicker: "What You're Building",
    title: "Your Grid's Favorite Thing",
    body: () => `
      <div class="hero-number">
        <b data-count="${type.count}">${type.count}</b>
        <span>${escapeHtml(type.label)} project${plural(type.count)}<br>${type.percent}% of ${model.year}</span>
      </div>
      <p class="slide-copy">This is the most common project category inside ${escapeHtml(model.utilityLabel)}'s ${model.year} work.</p>
    `,
  };
}

function biggestEraSlide(model) {
  const era = model.biggestEra;
  return {
    kicker: "Your Biggest Era",
    title: era.periodLabel,
    body: () => `
      <p class="slide-copy">${escapeHtml(model.utilityLabel)} peaks at ${era.maxCount} active or due project${plural(era.maxCount)}. That makes this your ${escapeHtml(era.theme)} era.</p>
      ${timeline(era.timeline)}
    `,
  };
}

function collaborationSlide(model) {
  const collaboration = model.topCollaboration;
  return {
    kicker: "Potential Coordination",
    title: "Your #1 Potential Collaboration",
    body: () => {
      if (!collaboration) {
        return `<p class="slide-copy">No cross-utility projects were found within ${MAX_DISTANCE_MI} miles of ${escapeHtml(model.utilityLabel)}'s ${model.year} project set.</p>`;
      }
      return `
        <div class="insight-split">
          <div>
            <span class="big-chip">${escapeHtml(formatUtility(collaboration.utility))}</span>
            <p class="slide-copy">${collaboration.count} project relationship${plural(collaboration.count)} surfaced within the coordination radius. You two might want to talk.</p>
          </div>
          <div class="stats-grid">
            ${statTile(collaboration.count, "nearby projects")}
            ${statTile(formatNumber(collaboration.averageDistance, 1), "avg miles apart")}
            ${statTile(collaboration.bestMonthsOverlap, "max overlap months")}
          </div>
        </div>
      `;
    },
  };
}

function missedConnectionsSlide(model) {
  return {
    kicker: "Almost There",
    title: "Missed Connections",
    body: () => `
      <p class="slide-copy">These ${escapeHtml(model.utilityLabel)} projects came close to another utility but fell below the primary coordination score.</p>
      <div class="project-list">
        ${model.missedConnections.slice(0, 3).map((candidate) => `
          <div class="project-chip">
            <strong>${escapeHtml(candidate.selectedProject.project_id)} - ${escapeHtml(candidate.selectedProject.project_name)}</strong>
            <span>${escapeHtml(formatUtility(candidate.otherUtility))} nearby · ${formatNumber(candidate.distanceMi, 1)} mi · ${candidate.monthsOverlap} overlap month${plural(candidate.monthsOverlap)}</span>
          </div>
        `).join("")}
      </div>
    `,
  };
}

function closestNeighborSlide(model) {
  return {
    kicker: "Nearby Context",
    title: "Closest Neighbor",
    body: () => {
      if (!model.nearestOther) {
        return `<p class="slide-copy">No other utility projects with usable coordinates were found near this ${model.year} set.</p>`;
      }
      return `
        <p class="slide-copy">No meaningful missed connections cleared the screen, so here is the nearest cross-utility project we can measure.</p>
        <div class="project-chip">
          <strong>${escapeHtml(formatUtility(model.nearestOther.otherUtility))}</strong>
          <span>${escapeHtml(model.nearestOther.otherProject.project_name)} · ${formatNumber(model.nearestOther.distanceMi, 1)} mi from ${escapeHtml(model.nearestOther.selectedProject.project_id)}</span>
        </div>
      `;
    },
  };
}

function hotspotSlide(model) {
  const hotspot = model.hotspot;
  return {
    kicker: "Where It Clusters",
    title: "Your Hotspot",
    body: () => {
      if (!hotspot || !hotspot.projectCount) {
        return `<p class="slide-copy">${escapeHtml(model.utilityLabel)} does not have enough located ${model.year} projects to calculate a geographic hotspot.</p>`;
      }
      return `
        <div class="insight-split">
          <div>
            <p class="slide-copy">${hotspot.projectCount} ${escapeHtml(model.utilityLabel)} project${plural(hotspot.projectCount)} cluster around ${escapeHtml(hotspot.label)}. ${hotspot.otherUtilityCount} other utilit${hotspot.otherUtilityCount === 1 ? "y is" : "ies are"} nearby.</p>
            <div class="stats-grid">
              ${statTile(hotspot.projectCount, "your projects")}
              ${statTile(hotspot.otherUtilityCount, "utilities nearby")}
              ${statTile(hotspot.yearRange, "active window")}
            </div>
          </div>
          ${miniMap(hotspot)}
        </div>
      `;
    },
  };
}

function topProjectSlide(model) {
  const top = model.topProject;
  return {
    kicker: "Standout Project",
    title: "Your Top Project",
    body: () => {
      if (!top) {
        return `<p class="slide-copy">No projects were available for this utility-year combination.</p>`;
      }
      return `
        <div class="project-chip">
          <strong>${escapeHtml(top.project.project_id)} - ${escapeHtml(top.project.project_name)}</strong>
          <span>${escapeHtml(top.reason)}</span>
        </div>
        <p class="slide-copy">This is the standout project using the strongest metric available in the dataset for ${escapeHtml(model.utilityLabel)}.</p>
      `;
    },
  };
}

function surpriseSlide(model) {
  const insight = model.surpriseInsight;
  return {
    kicker: "Cross-Utility Scan",
    title: "We Found Something",
    body: () => {
      if (!insight) {
        return `<p class="slide-copy">No cross-utility relationship could be calculated from the located projects for this selection.</p>`;
      }
      return `
        <p class="slide-copy">${escapeHtml(formatUtility(insight.otherUtility))} is building close to one of your ${model.year} projects. This is a potential coordination signal, not a confirmed recommendation.</p>
        <div class="stats-grid">
          ${statTile(formatNumber(insight.distanceMi, 1), "distance miles")}
          ${statTile(insight.monthsOverlap, "overlap months")}
          ${statTile(escapeHtml(insight.compatibilityLabel), "infrastructure")}
        </div>
        <div class="project-chip">
          <strong>${escapeHtml(insight.selectedProject.project_id)} + ${escapeHtml(insight.otherProject.project_id)}</strong>
          <span>${escapeHtml(insight.reason)}</span>
        </div>
      `;
    },
  };
}

function personalitySlide(model) {
  return {
    kicker: "Grid Personality",
    title: "Your Grid Type",
    body: () => `
      <div class="personality">
        <strong>${escapeHtml(model.gridPersonality.type)}</strong>
        <p class="slide-copy">${escapeHtml(model.gridPersonality.reason)}</p>
      </div>
    `,
  };
}

function shareSlide(model) {
  return {
    kicker: "Share Card",
    title: `${model.utilityLabel} ${model.year} Grid Wrapped`,
    body: () => `
      <div class="share-card">
        <div class="share-grid">
          ${statTile(model.totalProjects, "projects")}
          ${statTile(formatNumber(model.totalTransmissionMileage, 1), "known miles")}
          ${statTile(model.majorProjectCount, "major projects")}
          ${statTile(model.potentialCollaborations, "potential collaborations")}
        </div>
        <p class="slide-copy">Grid type: ${escapeHtml(model.gridPersonality.type)}</p>
        <button id="share-wrapped" class="primary-button" type="button">Share My Wrapped</button>
        <p id="share-note" class="share-note"></p>
      </div>
    `,
  };
}

function statTile(value, label) {
  const raw = String(value);
  const numeric = typeof value === "number" && Number.isFinite(value);
  return `
    <div class="stat-tile">
      <b ${numeric ? `data-count="${value}"` : ""}>${escapeHtml(raw)}</b>
      <span>${escapeHtml(label)}</span>
    </div>
  `;
}

function timeline(items) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return `
    <div class="timeline">
      ${items.map((item, index) => `
        <div class="bar" title="${item.year}: ${item.count} projects">
          <div class="bar-fill" style="height: ${Math.max(8, (item.count / max) * 100)}%; animation-delay: ${index * 45}ms"></div>
          <small>${item.year}</small>
        </div>
      `).join("")}
    </div>
  `;
}

function miniMap(hotspot) {
  return `
    <div class="mini-map" aria-label="Simplified project hotspot map">
      ${hotspot.mapPoints.map((point) => `
        <span class="map-dot ${point.isOther ? "other" : ""}" style="left: ${point.x}%; top: ${point.y}%"></span>
      `).join("")}
      <div class="map-caption">${escapeHtml(hotspot.label)} · green is selected utility · pink is nearby utility context</div>
    </div>
  `;
}

function animateCounters(root) {
  root.querySelectorAll("[data-count]").forEach((node) => {
    const target = Number(node.dataset.count);
    if (!Number.isFinite(target)) return;
    const hasDecimal = !Number.isInteger(target);
    const started = performance.now();
    const duration = 620;

    function tick(now) {
      const progress = Math.min(1, (now - started) / duration);
      const eased = 1 - (1 - progress) ** 3;
      const value = target * eased;
      node.textContent = hasDecimal ? formatNumber(value, 1) : String(Math.round(value));
      if (progress < 1) requestAnimationFrame(tick);
    }

    requestAnimationFrame(tick);
  });
}

function utilitySummaries() {
  const grouped = new Map();
  state.projects.forEach((project) => {
    if (!grouped.has(project.utility)) grouped.set(project.utility, []);
    grouped.get(project.utility).push(project);
  });

  return [...grouped.entries()]
    .map(([utility, projects]) => ({
      utility,
      label: formatUtility(utility),
      projectCount: projects.length,
      knownMiles: sumKnownMiles(projects),
      years: availableYearsFromProjects(projects),
    }))
    .sort((a, b) => b.projectCount - a.projectCount || a.label.localeCompare(b.label));
}

function availableYearsForUtility(utility) {
  const projects = state.projects.filter((project) => project.utility === utility);
  return availableYearsFromProjects(projects);
}

function availableYearsFromProjects(projects) {
  const allYears = [...new Set(projects.flatMap(projectYears))].sort((a, b) => a - b);
  const futureYears = allYears.filter((year) => year >= CURRENT_YEAR);
  return futureYears.length ? futureYears : allYears;
}

function projectsForUtilityYear(utility, year) {
  return state.projects.filter((project) => project.utility === utility && projectAppliesToYear(project, year));
}

function projectYears(project) {
  const start = parseDate(project.start_date);
  const service = parseDate(project.in_service_date);
  if (!start && !service) return [];

  let startYear = getYear(start || service);
  let endYear = getYear(service || start);
  if (startYear > endYear) [startYear, endYear] = [endYear, startYear];

  const years = [];
  for (let year = startYear; year <= endYear; year += 1) years.push(year);
  return years;
}

function projectAppliesToYear(project, year) {
  return projectYears(project).includes(Number(year));
}

function sumKnownMiles(projects) {
  return projects.reduce((total, project) => total + (num(project.length_mi) || 0), 0);
}

function countMajorProjects(projects) {
  return projects.filter((project) => {
    const voltage = num(project.voltage_kv);
    const cost = num(project.est_cost_usd);
    const miles = num(project.length_mi);
    return (voltage !== null && voltage >= 230) || (cost !== null && cost >= 10000000) || (miles !== null && miles >= 10);
  }).length;
}

function dominantType(projects) {
  if (!projects.length) return { key: "none", label: "No Dated", count: 0, percent: 0 };
  const counts = countBy(projects, (project) => project.project_type || "other");
  const [key, count] = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
  return {
    key,
    label: TYPE_LABELS[key] || titleCase(key),
    count,
    percent: Math.round((count / projects.length) * 100),
  };
}

function findBiggestEra(utility, utilityProjects) {
  const years = availableYearsFromProjects(utilityProjects);
  const timelineItems = years.map((year) => ({
    year,
    count: utilityProjects.filter((project) => projectAppliesToYear(project, year)).length,
  }));
  const maxCount = Math.max(0, ...timelineItems.map((item) => item.count));
  const peakYears = timelineItems.filter((item) => item.count === maxCount).map((item) => item.year);
  const peakRange = longestContiguousRange(peakYears);
  const periodProjects = utilityProjects.filter((project) => projectYears(project).some((year) => year >= peakRange[0] && year <= peakRange[1]));
  const theme = dominantType(periodProjects).label;

  return {
    timeline: timelineItems,
    maxCount,
    periodLabel: peakRange[0] === peakRange[1] ? String(peakRange[0]) : `${peakRange[0]}-${peakRange[1]}`,
    theme,
  };
}

function longestContiguousRange(years) {
  if (!years.length) return [CURRENT_YEAR, CURRENT_YEAR];
  let best = [years[0], years[0]];
  let current = [years[0], years[0]];
  for (let index = 1; index < years.length; index += 1) {
    if (years[index] === current[1] + 1) {
      current[1] = years[index];
    } else {
      if (current[1] - current[0] > best[1] - best[0]) best = current;
      current = [years[index], years[index]];
    }
  }
  return current[1] - current[0] > best[1] - best[0] ? current : best;
}

function buildCrossUtilityCandidates(primaryProjects, allProjects, selectedUtility) {
  const locatedPrimary = primaryProjects.filter(centerOf);
  const otherProjects = allProjects.filter((project) => project.utility !== selectedUtility && centerOf(project));
  const candidates = [];

  locatedPrimary.forEach((selectedProject) => {
    otherProjects.forEach((otherProject) => {
      const distanceMi = distanceBetweenCenters(selectedProject, otherProject);
      if (distanceMi === null || distanceMi > MAX_DISTANCE_MI) return;
      const timeGapDays = projectTimeGapDays(selectedProject, otherProject);
      const monthsOverlap = projectMonthsOverlap(selectedProject, otherProject);
      const voltageMatch = Boolean(selectedProject.voltage_kv) && String(selectedProject.voltage_kv) === String(otherProject.voltage_kv);
      const typeCompatible = Boolean(selectedProject.project_type) && selectedProject.project_type === otherProject.project_type;
      const confidence = Math.min(num(selectedProject.confidence) || 0, num(otherProject.confidence) || 0);
      const distanceScore = Math.max(0, 1 - distanceMi / MAX_DISTANCE_MI);
      const timeScore = timeGapDays === null ? Math.min(1, monthsOverlap / 12) : Math.max(0, 1 - timeGapDays / TIME_WINDOW_DAYS);
      const compatibilityScore = voltageMatch ? 1 : typeCompatible ? 0.65 : 0;
      const score = (0.6 * distanceScore + 0.3 * timeScore + 0.1 * compatibilityScore) * (0.5 + 0.5 * confidence);

      candidates.push({
        selectedProject,
        otherProject,
        otherUtility: otherProject.utility,
        distanceMi,
        timeGapDays,
        monthsOverlap,
        voltageMatch,
        typeCompatible,
        score,
        compatibilityLabel: voltageMatch ? "voltage match" : typeCompatible ? "type match" : "nearby work",
      });
    });
  });

  return candidates.sort((a, b) => b.score - a.score || a.distanceMi - b.distanceMi);
}

function findTopCollaboration(candidates) {
  if (!candidates.length) return null;
  const groups = new Map();

  candidates.forEach((candidate) => {
    if (!groups.has(candidate.otherUtility)) {
      groups.set(candidate.otherUtility, {
        utility: candidate.otherUtility,
        count: 0,
        distanceTotal: 0,
        scoreTotal: 0,
        bestMonthsOverlap: 0,
        bestCandidate: candidate,
      });
    }
    const group = groups.get(candidate.otherUtility);
    group.count += 1;
    group.distanceTotal += candidate.distanceMi;
    group.scoreTotal += candidate.score;
    group.bestMonthsOverlap = Math.max(group.bestMonthsOverlap, candidate.monthsOverlap);
    if (candidate.score > group.bestCandidate.score) group.bestCandidate = candidate;
  });

  return [...groups.values()]
    .map((group) => ({ ...group, averageDistance: group.distanceTotal / group.count }))
    .sort((a, b) => b.scoreTotal - a.scoreTotal || b.count - a.count || a.averageDistance - b.averageDistance)[0];
}

function findMissedConnections(candidates) {
  return candidates
    .filter((candidate) => candidate.score < COORDINATION_SCORE)
    .sort((a, b) => a.distanceMi - b.distanceMi || b.monthsOverlap - a.monthsOverlap)
    .slice(0, 4);
}

function findNearestOther(primaryProjects, allProjects, selectedUtility) {
  const locatedPrimary = primaryProjects.filter(centerOf);
  const otherProjects = allProjects.filter((project) => project.utility !== selectedUtility && centerOf(project));
  let nearest = null;

  locatedPrimary.forEach((selectedProject) => {
    otherProjects.forEach((otherProject) => {
      const distanceMi = distanceBetweenCenters(selectedProject, otherProject);
      if (distanceMi === null) return;
      const candidate = {
        selectedProject,
        otherProject,
        otherUtility: otherProject.utility,
        distanceMi,
        monthsOverlap: projectMonthsOverlap(selectedProject, otherProject),
        compatibilityLabel: String(selectedProject.voltage_kv) === String(otherProject.voltage_kv) ? "voltage match" : "nearest project",
      };
      if (!nearest || candidate.distanceMi < nearest.distanceMi) nearest = candidate;
    });
  });

  return nearest;
}

function findHotspot(primaryProjects, allProjects, selectedUtility) {
  const located = primaryProjects.filter(centerOf);
  if (!located.length) return null;

  let best = null;
  located.forEach((anchor) => {
    const anchorCenter = centerOf(anchor);
    const cluster = located.filter((project) => distanceBetweenPoints(anchorCenter, centerOf(project)) <= MAX_DISTANCE_MI);
    if (!best || cluster.length > best.cluster.length) best = { anchor, center: anchorCenter, cluster };
  });

  const otherNearby = allProjects
    .filter((project) => project.utility !== selectedUtility && centerOf(project))
    .map((project) => ({ project, distance: distanceBetweenPoints(best.center, centerOf(project)) }))
    .filter((item) => item.distance <= MAX_DISTANCE_MI)
    .sort((a, b) => a.distance - b.distance);
  const otherUtilities = new Set(otherNearby.map((item) => item.project.utility));
  const mapSource = [
    ...best.cluster.map((project) => ({ project, isOther: false })),
    ...otherNearby.slice(0, 12).map((item) => ({ project: item.project, isOther: true })),
  ];

  return {
    label: areaLabel(best.anchor),
    projectCount: best.cluster.length,
    otherUtilityCount: otherUtilities.size,
    yearRange: yearRangeForProjects(best.cluster),
    mapPoints: normalizeMapPoints(mapSource),
  };
}

function normalizeMapPoints(items) {
  const centers = items.map((item) => ({ ...centerOf(item.project), isOther: item.isOther }));
  const lats = centers.map((point) => point.lat);
  const lons = centers.map((point) => point.lon);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const latSpan = maxLat - minLat || 1;
  const lonSpan = maxLon - minLon || 1;

  return centers.map((point) => ({
    isOther: point.isOther,
    x: 10 + ((point.lon - minLon) / lonSpan) * 80,
    y: 90 - ((point.lat - minLat) / latSpan) * 80,
  }));
}

function findTopProject(primaryProjects, candidates) {
  if (!primaryProjects.length) return null;
  const connectionsByProject = countBy(
    candidates.filter((candidate) => candidate.score >= COORDINATION_SCORE),
    (candidate) => candidate.selectedProject.project_id
  );

  const scored = primaryProjects.map((project) => {
    const length = num(project.length_mi);
    const cost = num(project.est_cost_usd);
    const voltage = num(project.voltage_kv);
    const connections = connectionsByProject.get(project.project_id) || 0;

    if (length !== null) {
      return { project, rank: 4, value: length, reason: `${formatNumber(length, 1)} known line miles` };
    }
    if (cost !== null) {
      return { project, rank: 3, value: cost, reason: `${formatDollars(cost)} estimated cost` };
    }
    if (voltage !== null) {
      return { project, rank: 2, value: voltage, reason: `${formatNumber(voltage, 0)} kV listed voltage` };
    }
    return { project, rank: 1, value: connections, reason: `${connections} potential coordination link${plural(connections)}` };
  });

  return scored.sort((a, b) => b.rank - a.rank || b.value - a.value)[0];
}

function findSurpriseInsight(candidates, nearestOther) {
  const strongest = candidates[0] || nearestOther;
  if (!strongest) return null;
  const reasonParts = [
    `${formatNumber(strongest.distanceMi, 1)} miles apart`,
    `${strongest.monthsOverlap} month${plural(strongest.monthsOverlap)} of construction-window overlap`,
    strongest.compatibilityLabel,
  ];
  return {
    ...strongest,
    reason: `Flagged because the projects are ${reasonParts.join(", ")}.`,
  };
}

function chooseGridPersonality({ utilityYearProjects, dominantProjectType, potentialCollaborations, spreadMiles }) {
  if (potentialCollaborations >= 4) {
    return {
      type: "THE CONNECTOR",
      reason: `${potentialCollaborations} nearby cross-utility relationships cleared the potential coordination screen.`,
    };
  }
  if (spreadMiles >= 140) {
    return {
      type: "THE EXPANDER",
      reason: `Your ${utilityYearProjects.length} projects span about ${formatNumber(spreadMiles, 0)} miles across the service territory.`,
    };
  }
  if (["rebuild", "reconductor", "substation"].includes(dominantProjectType.key)) {
    return {
      type: "THE UPGRADER",
      reason: `${dominantProjectType.label} work is the dominant category for this year.`,
    };
  }
  return {
    type: "THE BUILDER",
    reason: `${dominantProjectType.label} work leads the plan, with ${utilityYearProjects.length} projects in the selected year.`,
  };
}

function projectSpreadMiles(projects) {
  const located = projects.filter(centerOf);
  let max = 0;
  for (let a = 0; a < located.length; a += 1) {
    for (let b = a + 1; b < located.length; b += 1) {
      max = Math.max(max, distanceBetweenCenters(located[a], located[b]) || 0);
    }
  }
  return max;
}

function projectWindow(project) {
  const service = parseDate(project.in_service_date);
  const start = parseDate(project.start_date);
  if (start && service) {
    return start <= service ? { start, end: service } : { start: service, end: start };
  }
  const only = start || service;
  if (!only) return null;
  const year = getYear(only);
  return {
    start: new Date(Date.UTC(year, 0, 1)),
    end: new Date(Date.UTC(year, 11, 31)),
  };
}

function projectMonthsOverlap(a, b) {
  const aw = projectWindow(a);
  const bw = projectWindow(b);
  if (!aw || !bw) return 0;
  const start = Math.max(aw.start.getTime(), bw.start.getTime());
  const end = Math.min(aw.end.getTime(), bw.end.getTime());
  if (end < start) return 0;
  return Math.max(1, Math.round((end - start) / (1000 * 60 * 60 * 24 * 30.44)));
}

function projectTimeGapDays(a, b) {
  const aDate = parseDate(a.in_service_date) || projectWindow(a)?.end;
  const bDate = parseDate(b.in_service_date) || projectWindow(b)?.end;
  if (!aDate || !bDate) return null;
  return Math.abs(Math.round((aDate - bDate) / (1000 * 60 * 60 * 24)));
}

function centerOf(project) {
  const lat = num(project.lat_center);
  const lon = num(project.lon_center);
  if (lat === null || lon === null) return null;
  return { lat, lon };
}

function distanceBetweenCenters(a, b) {
  const centerA = centerOf(a);
  const centerB = centerOf(b);
  if (!centerA || !centerB) return null;
  return distanceBetweenPoints(centerA, centerB);
}

function distanceBetweenPoints(a, b) {
  const radius = 3958.8;
  const toRad = (degrees) => (degrees * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * radius * Math.asin(Math.sqrt(h));
}

function areaLabel(project) {
  return project.endpoint_a || project.endpoint_b || project.state || project.project_id || "the project area";
}

function yearRangeForProjects(projects) {
  const years = [...new Set(projects.flatMap(projectYears))].sort((a, b) => a - b);
  if (!years.length) return "unknown";
  return years[0] === years[years.length - 1] ? String(years[0]) : `${years[0]}-${years[years.length - 1]}`;
}

function countBy(items, selector) {
  const counts = new Map();
  items.forEach((item) => {
    const key = selector(item);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return counts;
}

function parseDate(value) {
  if (!value) return null;
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
}

function getYear(date) {
  return date.getUTCFullYear();
}

function num(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatUtility(utility) {
  return UTILITY_LABELS[utility] || utility || "Unknown Utility";
}

function formatNumber(value, digits = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0";
  return number.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits > 0 && Math.abs(number % 1) > 0 ? digits : 0,
  });
}

function formatDollars(value) {
  if (value >= 1000000) return `$${formatNumber(value / 1000000, 1)}M`;
  if (value >= 1000) return `$${formatNumber(value / 1000, 0)}K`;
  return `$${formatNumber(value, 0)}`;
}

function plural(count) {
  return Number(count) === 1 ? "" : "s";
}

function titleCase(value) {
  return String(value || "other")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
