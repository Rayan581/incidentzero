/**
 * IncidentZero — Dark Neomorphic SRE Studio & Visualizer
 * Core Application Logic & SVG Canvas Engine
 */

// ── SVG Icon Registry (100% Vector SVGs, Zero Emojis) ────────────────────────
const SVG_ICONS = {
  server: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>`,
  database: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>`,
  shield: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,
  activity: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,
  terminal: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`,
  alert: `<svg class="svg-icon text-amber" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  check: `<svg class="svg-icon text-emerald" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  cross: `<svg class="svg-icon text-crimson" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  refresh: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>`,
  play: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
  pause: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>`,
  zap: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  cpu: `<svg class="svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>`,
};

// ── Application State ────────────────────────────────────────────────────────
const state = {
  traces: [],
  activeTraceName: "",
  events: [],
  currentStepIndex: 0,
  isPlaying: false,
  playbackSpeed: 1,
  playbackInterval: null,
  
  // Topology layout & status
  topology: null,
  selectedService: "redis-cache",
  serviceStatusMap: {},
  serviceMetricsMap: {},
  serviceLogsMap: {},
  
  // Active incident state
  incident: null,
  plan: null,
  worldVersion: 1,
  budgetLLM: 15,
  budgetTools: 15,

  // Live execution tracking
  liveRunId: null,
  livePollInterval: null,
};

// ── Fixed Topology Layout Coordinates (740 x 420 viewBox) ────────────────────
const NODE_COORDINATES = {
  "edge-gateway":     { x: 50,  y: 190, w: 110, h: 42 },
  "auth-service":     { x: 220, y: 45,  w: 110, h: 42 },
  "catalog-service":  { x: 220, y: 140, w: 115, h: 42 },
  "cart-service":     { x: 220, y: 240, w: 110, h: 42 },
  "checkout-service": { x: 220, y: 340, w: 120, h: 42 },
  "redis-cache":      { x: 410, y: 190, w: 110, h: 42 },
  "payment-service":  { x: 410, y: 290, w: 120, h: 42 },
  "inventory-service":{ x: 410, y: 360, w: 125, h: 42 },
  "order-service":    { x: 580, y: 290, w: 110, h: 42 },
  "order-db":         { x: 600, y: 360, w: 100, h: 42 },
};

// ── Initialization ───────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await loadSystemConfig();
  await loadTopology();
  await loadTracesList();
});

function setupEventListeners() {
  // Trace selector
  document.getElementById("btn-load-trace").addEventListener("click", () => {
    const sel = document.getElementById("trace-select");
    if (sel.value) loadTraceFile(sel.value);
  });
  document.getElementById("trace-select").addEventListener("change", (e) => {
    if (e.target.value) loadTraceFile(e.target.value);
  });

  // Replay controls
  document.getElementById("btn-replay-play").addEventListener("click", togglePlayback);
  document.getElementById("btn-replay-prev").addEventListener("click", () => stepTimeline(-1));
  document.getElementById("btn-replay-next").addEventListener("click", () => stepTimeline(1));
  document.getElementById("btn-replay-reset").addEventListener("click", () => jumpToStep(0));

  const slider = document.getElementById("timeline-slider");
  slider.addEventListener("input", (e) => jumpToStep(parseInt(e.target.value, 10)));

  // Speed buttons
  document.querySelectorAll(".speed-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".speed-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.playbackSpeed = parseFloat(btn.dataset.speed);
      if (state.isPlaying) {
        stopPlayback();
        startPlayback();
      }
    });
  });

  // Tweaks sliders
  setupSlider("slider-budget-llm", "val-budget-llm");
  setupSlider("slider-loop-guard", "val-loop-guard");

  // Tweaks actions
  document.getElementById("btn-start-run").addEventListener("click", triggerLiveAgentRun);
  document.getElementById("btn-save-tweaks").addEventListener("click", saveTweaksConfig);

  // Toggle tweaks panel on smaller screens
  document.getElementById("btn-toggle-tweaks").addEventListener("click", () => {
    const panel = document.getElementById("panel-tweaks");
    panel.style.display = panel.style.display === "none" ? "flex" : "none";
  });

  // Modal actions
  document.getElementById("btn-modal-approve").addEventListener("click", () => submitApproval(true));
  document.getElementById("btn-modal-deny").addEventListener("click", () => submitApproval(false));
}

function setupSlider(sliderId, valId) {
  const slider = document.getElementById(sliderId);
  const label = document.getElementById(valId);
  if (slider && label) {
    slider.addEventListener("input", (e) => {
      label.textContent = e.target.value;
    });
  }
}

// ── Data Fetching ─────────────────────────────────────────────────────────────
async function loadSystemConfig() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const data = await res.json();
    if (data.student_id) {
      document.getElementById("tweak-student-id").value = data.student_id;
    }
    if (data.groq_model) {
      document.getElementById("tweak-model").value = data.groq_model;
    }
  } catch (err) {
    console.warn("Could not fetch config:", err);
  }
}

async function loadTopology() {
  try {
    const res = await fetch("/api/topology");
    if (!res.ok) return;
    state.topology = await res.json();
    renderTopologySvg();
  } catch (err) {
    console.warn("Could not load topology:", err);
  }
}

async function loadTracesList() {
  try {
    const res = await fetch("/api/traces");
    if (!res.ok) return;
    const data = await res.json();
    state.traces = data.traces || [];
    
    const select = document.getElementById("trace-select");
    select.innerHTML = "";
    
    if (state.traces.length === 0) {
      select.innerHTML = "<option value=''>No traces found</option>";
      return;
    }

    state.traces.forEach((tr, i) => {
      const opt = document.createElement("option");
      opt.value = tr.name;
      opt.textContent = `${tr.name} (${Math.round(tr.size_bytes / 1024)} KB)`;
      if (i === 0) opt.selected = true;
      select.appendChild(opt);
    });

    if (state.traces.length > 0) {
      await loadTraceFile(state.traces[0].name);
    }
  } catch (err) {
    console.warn("Could not fetch traces:", err);
  }
}

async function loadTraceFile(filename) {
  try {
    stopPlayback();
    setSystemStatus("Loading trace...", "amber");
    const res = await fetch(`/api/trace?file=${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error("Trace file not found");
    const data = await res.json();
    
    state.activeTraceName = filename;
    state.events = data.events || [];
    state.currentStepIndex = 0;

    // Update scrubber slider
    const slider = document.getElementById("timeline-slider");
    slider.max = Math.max(0, state.events.length - 1);
    slider.value = 0;
    
    document.getElementById("timeline-end-label").textContent = `${state.events.length} Steps`;

    // Reset simulator visual state
    resetSimulationState();
    renderEventsFeed();
    jumpToStep(0);
    setSystemStatus(`Trace Loaded (${state.events.length} events)`, "healthy");
  } catch (err) {
    setSystemStatus("Trace load error", "degraded");
    console.error(err);
  }
}

// ── SVG Topology Rendering ────────────────────────────────────────────────────
function renderTopologySvg() {
  const svg = document.getElementById("topology-svg");
  if (!svg || !state.topology) return;
  svg.innerHTML = "";

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.innerHTML = `
    <linearGradient id="edge-grad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#00e5ff" stop-opacity="0.2"/>
      <stop offset="100%" stop-color="#a855f7" stop-opacity="0.4"/>
    </linearGradient>
    <filter id="glow-cyan" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="4" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  `;
  svg.appendChild(defs);

  // Render Edges
  const edgeGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
  edgeGroup.setAttribute("class", "topo-edges-group");

  state.topology.edges.forEach((edge) => {
    const src = NODE_COORDINATES[edge.source];
    const tgt = NODE_COORDINATES[edge.target];
    if (!src || !tgt) return;

    const x1 = src.x + src.w;
    const y1 = src.y + src.h / 2;
    const x2 = tgt.x;
    const y2 = tgt.y + tgt.h / 2;
    const dx = Math.abs(x2 - x1) * 0.5;

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    path.setAttribute("d", d);
    path.setAttribute("class", "topo-edge");
    path.setAttribute("data-src", edge.source);
    path.setAttribute("data-tgt", edge.target);

    // Highlight critical path
    const isCritical = state.topology.nodes.find(n => n.id === edge.source)?.is_critical &&
                       state.topology.nodes.find(n => n.id === edge.target)?.is_critical;
    if (isCritical) {
      path.classList.add("critical-path");
    }

    edgeGroup.appendChild(path);
  });
  svg.appendChild(edgeGroup);

  // Render Nodes
  const nodeGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
  nodeGroup.setAttribute("class", "topo-nodes-group");

  state.topology.nodes.forEach((node) => {
    const coord = NODE_COORDINATES[node.id];
    if (!coord) return;

    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", `topo-node ${node.id === state.selectedService ? "selected" : ""}`);
    g.setAttribute("id", `node-${node.id}`);
    g.setAttribute("transform", `translate(${coord.x}, ${coord.y})`);

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", coord.w);
    rect.setAttribute("height", coord.h);
    rect.setAttribute("class", "topo-node-box");

    // Status beacon dot inside node
    const beacon = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    beacon.setAttribute("cx", 14);
    beacon.setAttribute("cy", coord.h / 2);
    beacon.setAttribute("r", 4);
    beacon.setAttribute("class", "node-beacon-dot");
    beacon.setAttribute("fill", "#10b981");

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", coord.w / 2 + 6);
    text.setAttribute("y", coord.h / 2);
    text.setAttribute("class", "topo-node-text");
    text.textContent = node.label;

    g.appendChild(rect);
    g.appendChild(beacon);
    g.appendChild(text);

    g.addEventListener("click", () => selectServiceNode(node.id));
    nodeGroup.appendChild(g);
  });
  svg.appendChild(nodeGroup);
}

function updateTopologyVisualState() {
  if (!state.topology) return;
  state.topology.nodes.forEach((node) => {
    const el = document.getElementById(`node-${node.id}`);
    if (!el) return;

    const isDegraded = state.serviceStatusMap[node.id] === false;
    const isSelected = node.id === state.selectedService;

    el.classList.toggle("degraded", isDegraded);
    el.classList.toggle("selected", isSelected);

    const beacon = el.querySelector(".node-beacon-dot");
    if (beacon) {
      beacon.setAttribute("fill", isDegraded ? "#f43f5e" : "#10b981");
    }
  });
}

function selectServiceNode(serviceId) {
  state.selectedService = serviceId;
  updateTopologyVisualState();
  updateServiceInspector();
}

function updateServiceInspector() {
  const nameEl = document.getElementById("inspector-service-name");
  const tagEl = document.getElementById("inspector-status-tag");
  const repEl = document.getElementById("insp-replicas");
  const errEl = document.getElementById("insp-error-rate");
  const p95El = document.getElementById("insp-p95");
  const depsEl = document.getElementById("insp-deps");
  const logsEl = document.getElementById("insp-logs");

  const service = state.selectedService;
  nameEl.textContent = service;

  const isDegraded = state.serviceStatusMap[service] === false;
  tagEl.textContent = isDegraded ? "DEGRADED" : "HEALTHY";
  tagEl.className = `status-tag ${isDegraded ? "status-degraded" : "status-healthy"}`;

  const metrics = state.serviceMetricsMap[service] || {};
  repEl.textContent = metrics.replicas ?? (isDegraded ? 2 : 3);
  
  if (metrics.error_rate !== undefined) {
    errEl.textContent = `${(metrics.error_rate * 100).toFixed(1)}%`;
  } else {
    errEl.textContent = isDegraded ? "14.0%" : "0.2%";
  }

  p95El.textContent = metrics.p95_ms ? `${metrics.p95_ms}ms` : (isDegraded ? "800ms" : "42ms");

  const nodeData = state.topology?.nodes.find(n => n.id === service);
  depsEl.textContent = `${nodeData?.upstream.length || 0} callers, ${nodeData?.downstream.length || 0} deps`;

  // Logs
  const logs = state.serviceLogsMap[service];
  if (logs && logs.length > 0) {
    logsEl.innerHTML = logs.map(l => {
      const cls = l.includes("ERROR") ? "log-error" : (l.includes("WARN") ? "log-warn" : "log-info");
      return `<div class="log-entry ${cls}">${escapeHtml(l)}</div>`;
    }).join("");
  } else {
    logsEl.innerHTML = `<div class="log-entry log-info">INFO: ${service} heartbeat ok</div>`;
  }
}

// ── Timeline Replay Engine ────────────────────────────────────────────────────
function resetSimulationState() {
  state.serviceStatusMap = { "redis-cache": false };
  state.serviceMetricsMap = {};
  state.serviceLogsMap = {};
  state.worldVersion = 1;
  state.budgetLLM = 15;
  state.budgetTools = 15;
  state.incident = null;
  state.plan = null;
}

function jumpToStep(targetIndex) {
  if (state.events.length === 0) return;
  targetIndex = Math.max(0, Math.min(targetIndex, state.events.length - 1));
  state.currentStepIndex = targetIndex;

  // Rebuild state incrementally up to targetIndex
  resetSimulationState();

  for (let i = 0; i <= targetIndex; i++) {
    applyEventToState(state.events[i]);
  }

  // Update DOM widgets
  updateHeaderBadges();
  updateIncidentCard();
  updatePlanCard();
  updateTopologyVisualState();
  updateServiceInspector();
  updateTimelineScrubber();
  highlightActiveEventCard(targetIndex);
}

function stepTimeline(delta) {
  const newIndex = state.currentStepIndex + delta;
  if (newIndex >= 0 && newIndex < state.events.length) {
    jumpToStep(newIndex);
  } else if (newIndex >= state.events.length) {
    stopPlayback();
  }
}

function togglePlayback() {
  if (state.isPlaying) {
    stopPlayback();
  } else {
    startPlayback();
  }
}

function startPlayback() {
  if (state.events.length === 0) return;
  state.isPlaying = true;
  document.getElementById("play-pause-icon").innerHTML = SVG_ICONS.pause;

  if (state.currentStepIndex >= state.events.length - 1) {
    jumpToStep(0);
  }

  const baseDelay = 1000 / state.playbackSpeed;
  state.playbackInterval = setInterval(() => {
    if (state.currentStepIndex < state.events.length - 1) {
      stepTimeline(1);
    } else {
      stopPlayback();
    }
  }, baseDelay);
}

function stopPlayback() {
  state.isPlaying = false;
  document.getElementById("play-pause-icon").innerHTML = SVG_ICONS.play;
  if (state.playbackInterval) {
    clearInterval(state.playbackInterval);
    state.playbackInterval = null;
  }
}

function updateTimelineScrubber() {
  const slider = document.getElementById("timeline-slider");
  slider.value = state.currentStepIndex;
  
  const curEventEl = document.getElementById("timeline-current-event");
  const ev = state.events[state.currentStepIndex];
  if (ev) {
    let name = ev.event;
    if (ev.payload?.call?.name) name = `Tool: ${ev.payload.call.name}`;
    else if (ev.payload?.plan) name = "Plan Created";
    curEventEl.textContent = `[${state.currentStepIndex + 1}/${state.events.length}] ${name}`;
  }
  document.getElementById("step-counter").textContent = `Step ${state.currentStepIndex + 1} / ${state.events.length}`;
}

// ── State Accumulator ─────────────────────────────────────────────────────────
function applyEventToState(eventItem) {
  if (!eventItem) return;
  const { event, payload } = eventItem;

  // Deduct budget
  if (event === "model_reply") {
    state.budgetLLM = Math.max(0, state.budgetLLM - 1);
  } else if (event === "tool_result") {
    state.budgetTools = Math.max(0, state.budgetTools - 1);
  }

  // Initial Bootstrap or get_incident
  if (event === "bootstrap_incident" && payload?.incident?.data) {
    state.incident = payload.incident.data;
  } else if (payload?.call?.name === "get_incident" && payload?.result?.data) {
    state.incident = payload.result.data;
  }

  // Plan creation / revision
  if (event === "plan_created" && payload?.plan) {
    state.plan = parseAgentPlanString(payload.plan);
  }

  // Tool results
  if (event === "tool_result" && payload?.result) {
    const res = payload.result;
    const call = payload.call;
    if (res.world_version) state.worldVersion = res.world_version;

    // Service health updates
    if (call?.name === "get_service_health" && res.data) {
      state.serviceStatusMap[res.data.service] = res.data.healthy;
    }
    // Restart service updates
    if (call?.name === "restart_service" && res.status === "ok") {
      state.serviceStatusMap[call.arguments.service] = true;
    }
    // Verify recovery
    if (call?.name === "verify_recovery" && res.data) {
      if (res.data.criteria_met) {
        state.serviceStatusMap["redis-cache"] = true;
      }
    }
    // Metrics
    if (call?.name === "get_metrics" && res.data) {
      state.serviceMetricsMap[res.data.service] = res.data;
    }
    // Logs
    if (call?.name === "get_logs" && res.data?.entries) {
      state.serviceLogsMap[res.data.service] = res.data.entries;
    }
  }
}

function parseAgentPlanString(planStr) {
  if (typeof planStr === "object") return planStr;
  try {
    const hypMatch = planStr.match(/hypothesis='(.*?)'/s);
    const ratMatch = planStr.match(/rationale_summary='(.*?)'/s);
    return {
      hypothesis: hypMatch ? hypMatch[1] : "Remediate service failure",
      rationale: ratMatch ? ratMatch[1] : "",
      revision: 0,
      steps: [
        { id: "S1", title: "Query system telemetry and logs", status: "completed" },
        { id: "S2", title: "Analyze cache key inconsistency", status: "completed" },
        { id: "S3", title: "Execute safe restart on redis-cache", status: "completed" },
        { id: "S4", title: "Verify checkout latency <=800ms and error_rate <=1%", status: "in_progress" },
        { id: "S5", title: "Submit incident closure", status: "pending" },
      ]
    };
  } catch (err) {
    return { hypothesis: "Investigate and resolve incident", revision: 0, steps: [] };
  }
}

// ── UI Widget Updates ─────────────────────────────────────────────────────────
function updateHeaderBadges() {
  document.getElementById("badge-world-version").textContent = `v${state.worldVersion}`;
  document.getElementById("badge-budget-llm").textContent = `${state.budgetLLM}/15`;
  document.getElementById("badge-budget-tools").textContent = `${state.budgetTools}/15`;
}

function updateIncidentCard() {
  if (!state.incident) return;
  document.getElementById("inc-id").textContent = state.incident.incident_id || "INC-726259";
  document.getElementById("inc-severity").textContent = state.incident.severity || "SEV-1";
  document.getElementById("inc-title").textContent = state.incident.title || "Production Service Degradation";
  document.getElementById("inc-impact").textContent = state.incident.customer_impact || "Elevated error rate";
  document.getElementById("inc-suspected").textContent = state.incident.suspected_service || "redis-cache";
  document.getElementById("inc-objective").textContent = state.incident.objective || "Restore service SLOs";
}

function updatePlanCard() {
  if (!state.plan) return;
  document.getElementById("plan-revision").textContent = `Rev #${state.plan.revision ?? 0}`;
  document.getElementById("plan-hypothesis").textContent = state.plan.hypothesis;

  const list = document.getElementById("plan-steps-list");
  if (state.plan.steps && state.plan.steps.length > 0) {
    list.innerHTML = state.plan.steps.map((st, i) => `
      <div class="step-item ${st.status === 'in_progress' ? 'active' : (st.status === 'completed' ? 'completed' : '')}">
        <div class="step-left">
          <span class="step-badge">${st.id || `S${i+1}`}</span>
          <span>${escapeHtml(st.title || st.objective || `Milestone ${i+1}`)}</span>
        </div>
        <span class="step-status-pill step-${st.status === 'completed' ? 'done' : (st.status === 'in_progress' ? 'current' : 'pending')}">
          ${st.status}
        </span>
      </div>
    `).join("");
  }
}

// ── Events Feed Rendering ────────────────────────────────────────────────────
function renderEventsFeed() {
  const container = document.getElementById("events-stream");
  container.innerHTML = "";

  state.events.forEach((ev, idx) => {
    const card = document.createElement("div");
    card.className = "event-card";
    card.id = `event-card-${idx}`;

    let iconHtml = SVG_ICONS.activity;
    let titleHtml = ev.event;
    let metaHtml = "";
    let bodyHtml = "";

    if (ev.event === "plan_created") {
      iconHtml = SVG_ICONS.shield;
      titleHtml = `Plan Formulated`;
      bodyHtml = `<div class="payload-block">Hypothesis: ${escapeHtml(ev.payload?.plan?.substring(0, 180))}...</div>`;
    } else if (ev.event === "model_reply") {
      iconHtml = SVG_ICONS.terminal;
      const call = ev.payload?.tool_calls?.[0];
      if (call) {
        titleHtml = `Agent Action Proposed: <span class="tool-name-tag">${call.name}</span>`;
        bodyHtml = `<div class="payload-block">${escapeHtml(JSON.stringify(call.arguments, null, 2))}</div>`;
      } else {
        titleHtml = `Agent Reasoning`;
        bodyHtml = `<div class="payload-block">${escapeHtml(ev.payload?.content || "Deliberating...")}</div>`;
      }
    } else if (ev.event === "tool_result") {
      const callName = ev.payload?.call?.name || "tool";
      const status = ev.payload?.result?.status || "ok";
      const isOk = status === "ok";
      iconHtml = isOk ? SVG_ICONS.check : SVG_ICONS.alert;
      
      titleHtml = `Tool Executed: <span class="tool-name-tag">${callName}</span>`;
      if (ev.payload?.result?.evidence_id) {
        metaHtml = `<span class="evidence-tag">${ev.payload.result.evidence_id}</span>`;
      }
      bodyHtml = `<div class="payload-block">${escapeHtml(JSON.stringify(ev.payload.result, null, 2))}</div>`;
    } else if (ev.event.includes("error")) {
      iconHtml = SVG_ICONS.cross;
      titleHtml = `<span class="text-crimson">Execution Exception</span>`;
      bodyHtml = `<div class="payload-block">${escapeHtml(JSON.stringify(ev.payload, null, 2))}</div>`;
    } else {
      bodyHtml = `<div class="payload-block">${escapeHtml(JSON.stringify(ev.payload, null, 2))}</div>`;
    }

    card.innerHTML = `
      <div class="event-card-top">
        <div class="event-type-badge">
          ${iconHtml}
          <span>${titleHtml}</span>
        </div>
        <div class="event-meta">
          ${metaHtml}
          <span class="step-badge">#${idx + 1}</span>
        </div>
      </div>
      ${bodyHtml}
    `;

    card.addEventListener("click", () => jumpToStep(idx));
    container.appendChild(card);
  });
}

function highlightActiveEventCard(index) {
  document.querySelectorAll(".event-card").forEach((card, idx) => {
    card.classList.toggle("active-step", idx === index);
  });
  const activeCard = document.getElementById(`event-card-${index}`);
  if (activeCard) {
    activeCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

// ── Live Execution & Human Approval ──────────────────────────────────────────
async function triggerLiveAgentRun() {
  const model = document.getElementById("tweak-model").value;
  const scenario = document.getElementById("tweak-scenario").value;
  const studentId = document.getElementById("tweak-student-id").value;
  const approvalMode = document.querySelector("input[name='approval_mode']:checked")?.value || "interactive";

  setSystemStatus("Starting autonomous run...", "amber");
  stopPlayback();

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, scenario, student_id: studentId, approval_mode: approvalMode }),
    });
    const data = await res.json();
    state.liveRunId = data.run_id;
    state.events = [];
    renderEventsFeed();

    // Start polling run status
    if (state.livePollInterval) clearInterval(state.livePollInterval);
    state.livePollInterval = setInterval(pollLiveRunStatus, 600);
  } catch (err) {
    setSystemStatus("Failed to start run", "degraded");
    console.error(err);
  }
}

async function pollLiveRunStatus() {
  if (!state.liveRunId) return;
  try {
    const res = await fetch(`/api/run_status?run_id=${state.liveRunId}`);
    if (!res.ok) return;
    const data = await res.json();

    // Check for pending human approval
    if (data.pending_approval) {
      showApprovalModal(data.pending_approval);
    } else {
      hideApprovalModal();
    }

    // Update events
    if (data.events && data.events.length > state.events.length) {
      state.events = data.events;
      renderEventsFeed();
      jumpToStep(state.events.length - 1);
    }

    if (data.status === "completed" || data.status === "failed") {
      clearInterval(state.livePollInterval);
      state.livePollInterval = null;
      setSystemStatus(`Run ${data.status.toUpperCase()} (${state.events.length} steps)`, data.status === "completed" ? "healthy" : "degraded");
      await loadTracesList(); // refresh traces list with new trace
    }
  } catch (err) {
    console.warn("Poll error:", err);
  }
}

function showApprovalModal(appr) {
  const modal = document.getElementById("approval-modal");
  document.getElementById("modal-action-name").textContent = appr.action;
  document.getElementById("modal-arguments").textContent = JSON.stringify(appr.arguments);
  document.getElementById("modal-justification").textContent = appr.justification || "Remediation action";
  modal.classList.remove("hidden");
}

function hideApprovalModal() {
  document.getElementById("approval-modal").classList.add("hidden");
}

async function submitApproval(approved) {
  if (!state.liveRunId) return;
  try {
    await fetch("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: state.liveRunId, approved }),
    });
    hideApprovalModal();
  } catch (err) {
    console.error("Failed to submit approval:", err);
  }
}

async function saveTweaksConfig() {
  const model = document.getElementById("tweak-model").value;
  const studentId = document.getElementById("tweak-student-id").value;
  try {
    const res = await fetch("/api/save_config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ groq_model: model, student_id: studentId }),
    });
    if (res.ok) {
      setSystemStatus("Config saved to .env", "healthy");
    }
  } catch (err) {
    setSystemStatus("Config save failed", "degraded");
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function setSystemStatus(text, type) {
  const textEl = document.getElementById("system-status-text");
  const beacon = document.getElementById("system-beacon");
  textEl.textContent = text;
  beacon.style.background = type === "healthy" ? "var(--status-healthy)" : (type === "amber" ? "var(--status-warning)" : "var(--status-degraded)");
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
