const PAIRS_URL = "/viewer/data/pairs.json";
// The viewer is served statically (port 8000) but app.py's Flask backend
// runs separately (port 5000) - a relative fetch("/process") would resolve
// against the viewer's own origin and hit the static server instead, which
// has no such route. Must be absolute.
const PROCESS_URL = "http://localhost:5000/process";
const REALIGN_URL = "http://localhost:5000/realign";
const TICK_MS = 1000 / 60;
// How many frames ahead of the current playhead to keep preloaded in memory,
// per side. Frames are downloaded well before they're needed so tick() never
// blocks on a network fetch; frames more than EVICT_BEHIND behind the
// playhead are dropped so memory doesn't grow to hold the whole clip.
const PRELOAD_AHEAD = 40;
const EVICT_BEHIND = 5;
// Caps how much elapsed wall-clock time a single tick() call will convert into
// catch-up steps. Browsers throttle requestAnimationFrame to ~1/sec (or stop it
// entirely) for backgrounded/minimized tabs, so switching away during playback
// and back can hand tick() a multi-second delta in one callback. Without this
// cap, the accumulator's catch-up loop races through hundreds of path steps in
// a single call trying to "make up" that time - visually a jump straight to
// (or near) the end. Clamping means a long pause just resumes smoothly from
// wherever playback was, instead of racing to catch up.
const MAX_DELTA_MS = 250;

const el = {
  picker: document.getElementById("pairPicker"),
  subtitle: document.getElementById("pairSubtitle"),
  insightsLink: document.getElementById("insightsLink"),
  canvasA: document.getElementById("canvasA"),
  canvasB: document.getElementById("canvasB"),
  labelA: document.getElementById("labelA"),
  labelB: document.getElementById("labelB"),
  timeA: document.getElementById("timeA"),
  timeB: document.getElementById("timeB"),
  playPause: document.getElementById("playPause"),
  scrubber: document.getElementById("scrubber"),
  stepReadout: document.getElementById("stepReadout"),
  graph: document.getElementById("graph"),
  uploadForm: document.getElementById("uploadForm"),
  fileA: document.getElementById("fileA"),
  fileB: document.getElementById("fileB"),
  uploadSubmit: document.getElementById("uploadSubmit"),
  uploadStatus: document.getElementById("uploadStatus"),
  realignPanel: document.getElementById("realignPanel"),
  realignForm: document.getElementById("realignForm"),
  endEventA: document.getElementById("endEventA"),
  endEventB: document.getElementById("endEventB"),
  endEventALabel: document.getElementById("endEventALabel"),
  endEventBLabel: document.getElementById("endEventBLabel"),
  realignSubmit: document.getElementById("realignSubmit"),
  realignStatus: document.getElementById("realignStatus"),
};

// Loads and displays video frames as individual JPEGs drawn to a <canvas>,
// instead of seeking a <video> element's .currentTime. Seeking a compressed
// video on nearly every DTW path step turned out to be the actual source of
// viewer lag (codec seek latency) - drawImage from an already-decoded <img>
// has none of that cost. Keeps a small rolling window of frames preloaded
// ahead of the playhead rather than fetching on demand or holding the whole
// clip in memory.
class FrameCache {
  constructor(framesDir, frameCount, canvas) {
    this.framesDir = framesDir;
    this.frameCount = frameCount;
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.images = new Map(); // frameIndex -> HTMLImageElement
    this.lastShown = -1;
  }

  _url(index) {
    return `${this.framesDir}${String(index).padStart(6, "0")}.jpg`;
  }

  _getOrLoad(index) {
    let img = this.images.get(index);
    if (!img) {
      img = new Image();
      img.src = this._url(index);
      // A burst of ~80 concurrent preload requests (both sides, on startup)
      // can exceed the dev server's connection backlog and get refused
      // outright - rare, but with no retry that frame would stay a
      // permanently blank/stale gap. Dropping the cache entry on error lets
      // the next access (a later preload pass, or scrubbing back over it)
      // create a fresh Image and retry the request instead.
      img.addEventListener("error", () => this.images.delete(index), { once: true });
      this.images.set(index, img);
    }
    return img;
  }

  show(index) {
    index = Math.max(0, Math.min(this.frameCount - 1, index));
    if (index === this.lastShown) return;
    this.lastShown = index;

    const img = this._getOrLoad(index);
    const draw = () => this.ctx.drawImage(img, 0, 0, this.canvas.width, this.canvas.height);
    if (img.complete && img.naturalWidth > 0) {
      draw();
    } else {
      // Only draw when it finishes loading if the playhead hasn't already
      // moved past this frame - otherwise a slow-to-arrive image could
      // paint over a later, already-correct frame.
      img.addEventListener("load", () => {
        if (this.lastShown === index) draw();
      });
    }

    this._preloadAhead(index);
    this._evictBehind(index);
  }

  _preloadAhead(index) {
    const end = Math.min(this.frameCount - 1, index + PRELOAD_AHEAD);
    for (let i = index + 1; i <= end; i++) this._getOrLoad(i);
  }

  _evictBehind(index) {
    const cutoff = index - EVICT_BEHIND;
    for (const key of this.images.keys()) {
      if (key < cutoff) this.images.delete(key);
    }
  }
}

let pairsManifest = [];
let data = null;
let frameCacheA = null;
let frameCacheB = null;
let currentStep = 0;
let playing = false;
let rafId = null;
let lastFrameTime = null;
let accumulatorMs = 0;

const GRAPH = { width: 1200, height: 260, marginLeft: 44, marginRight: 10, marginTop: 10, marginBottom: 22 };

async function loadPairsManifest() {
  const res = await fetch(PAIRS_URL);
  pairsManifest = await res.json();
  el.picker.innerHTML = "";
  for (const pair of pairsManifest) {
    const opt = document.createElement("option");
    opt.value = pair.data_path;
    opt.textContent = pair.name.replace(/_/g, " ");
    el.picker.appendChild(opt);
  }
}

async function loadPair(dataPath) {
  pausePlayback();
  const res = await fetch(dataPath);
  data = await res.json();
  data._dataDir = dataPath.substring(0, dataPath.lastIndexOf("/") + 1);

  el.canvasA.width = data.frame_width_a;
  el.canvasA.height = data.frame_height_a;
  el.canvasB.width = data.frame_width_b;
  el.canvasB.height = data.frame_height_b;
  frameCacheA = new FrameCache(data.frames_dir_a, data.frame_count_a, el.canvasA);
  frameCacheB = new FrameCache(data.frames_dir_b, data.frame_count_b, el.canvasB);

  el.labelA.textContent = data.label_a;
  el.labelB.textContent = data.label_b;
  el.subtitle.textContent = `${data.joints_used.length} joints compared, ${data.joints_excluded.length} excluded for this pair`;
  el.insightsLink.href = `insights.html?pair=${encodeURIComponent(data.pair_name)}`;

  el.endEventALabel.firstChild.textContent = `End time for ${data.label_a} (s)`;
  el.endEventBLabel.firstChild.textContent = `End time for ${data.label_b} (s)`;
  el.endEventA.value = "";
  el.endEventB.value = "";
  el.realignPanel.hidden = false;

  el.scrubber.max = String(data.steps.length - 1);
  currentStep = 0;

  renderGraph();
  seekToStep(0);
}

function formatSeconds(t) {
  return `${t.toFixed(2)}s`;
}

function seekToStep(i) {
  currentStep = Math.max(0, Math.min(data.steps.length - 1, i));
  const step = data.steps[currentStep];

  frameCacheA.show(step.frame_a);
  frameCacheB.show(step.frame_b);

  el.timeA.textContent = formatSeconds(step.timestamp_a);
  el.timeB.textContent = formatSeconds(step.timestamp_b);
  el.scrubber.value = String(currentStep);
  el.stepReadout.textContent = `step ${currentStep} / ${data.steps.length - 1}`;

  updateGraphMarker();
}

function tick(now) {
  if (!playing) return;
  if (lastFrameTime === null) lastFrameTime = now;
  const delta = Math.min(now - lastFrameTime, MAX_DELTA_MS);
  accumulatorMs += delta;
  lastFrameTime = now;

  let next = currentStep;
  while (accumulatorMs >= TICK_MS) {
    accumulatorMs -= TICK_MS;
    if (next < data.steps.length - 1) {
      next += 1;
    } else {
      pausePlayback();
      break;
    }
  }
  seekToStep(next);
  if (playing) rafId = requestAnimationFrame(tick);
}

function startPlayback() {
  if (playing || !data) return;
  playing = true;
  lastFrameTime = null;
  accumulatorMs = 0;
  el.playPause.textContent = "Pause";
  rafId = requestAnimationFrame(tick);
}

function pausePlayback() {
  playing = false;
  el.playPause.textContent = "Play";
  if (rafId) cancelAnimationFrame(rafId);
}

function stepX(step) {
  const g = GRAPH;
  const plotWidth = g.width - g.marginLeft - g.marginRight;
  return g.marginLeft + (step / (data.steps.length - 1)) * plotWidth;
}

function valueY(value, maxValue) {
  const g = GRAPH;
  const plotHeight = g.height - g.marginTop - g.marginBottom;
  return g.marginTop + (1 - value / maxValue) * plotHeight;
}

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function renderGraph() {
  const g = GRAPH;
  const svg = el.graph;
  svg.innerHTML = "";
  svg.setAttribute("viewBox", `0 0 ${g.width} ${g.height}`);

  const maxValue = Math.max(1, ...data.steps.filter((s) => s.divergence !== null).map((s) => s.divergence));
  const plotBottom = g.height - g.marginBottom;

  // Region background bands. Each label is clipped to its own band's
  // rect so adjacent narrow regions (common with several short DTW
  // stalls close together) never bleed their text into each other.
  const defs = svgEl("defs", {});
  svg.appendChild(defs);

  data.regions.forEach((region, i) => {
    const x1 = stepX(region.start_step);
    const x2 = stepX(region.end_step);
    const bandWidth = Math.max(1, x2 - x1);
    const bandHeight = plotBottom - g.marginTop;
    const color = region.type === "stall" ? "var(--stall)" : "var(--ended)";

    svg.appendChild(
      svgEl("rect", { x: x1, y: g.marginTop, width: bandWidth, height: bandHeight, fill: color, opacity: 0.25 })
    );

    const clipId = `region-clip-${i}`;
    const clipPath = svgEl("clipPath", { id: clipId });
    clipPath.appendChild(svgEl("rect", { x: x1, y: g.marginTop, width: bandWidth, height: bandHeight }));
    defs.appendChild(clipPath);

    const label = svgEl("text", {
      x: x1 + 3,
      y: g.marginTop + 12,
      fill: "var(--text-dim)",
      "font-size": "9",
      "clip-path": `url(#${clipId})`,
    });
    label.textContent = region.label;
    svg.appendChild(label);
  });

  // Y axis gridlines/labels (0, half, max)
  for (const frac of [0, 0.5, 1]) {
    const y = valueY(maxValue * frac, maxValue);
    svg.appendChild(
      svgEl("line", { x1: g.marginLeft, x2: g.width - g.marginRight, y1: y, y2: y, stroke: "#2f333a", "stroke-width": 1 })
    );
    const label = svgEl("text", { x: 2, y: y + 3, fill: "var(--text-dim)", "font-size": "9" });
    label.textContent = (maxValue * frac).toFixed(0) + "°";
    svg.appendChild(label);
  }

  // Divergence line, broken into segments at null gaps
  let segment = [];
  const segments = [];
  for (const step of data.steps) {
    if (step.divergence === null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else {
      segment.push(step);
    }
  }
  if (segment.length) segments.push(segment);

  for (const seg of segments) {
    const points = seg.map((s) => `${stepX(s.step)},${valueY(s.divergence, maxValue)}`).join(" ");
    svg.appendChild(
      svgEl("polyline", { points, fill: "none", stroke: "var(--divergence-line)", "stroke-width": 1.5 })
    );
  }

  // Current-position marker (updated on every seek)
  const marker = svgEl("line", {
    id: "graphMarker",
    x1: stepX(0),
    x2: stepX(0),
    y1: g.marginTop,
    y2: plotBottom,
    stroke: "#fff",
    "stroke-width": 1,
    "stroke-dasharray": "3,3",
  });
  svg.appendChild(marker);

  svg._maxValue = maxValue;
}

function updateGraphMarker() {
  const marker = document.getElementById("graphMarker");
  if (!marker) return;
  const x = stepX(currentStep);
  marker.setAttribute("x1", x);
  marker.setAttribute("x2", x);
}

function graphClickToStep(evt) {
  const svg = el.graph;
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX;
  pt.y = evt.clientY;
  const svgPoint = pt.matrixTransform(svg.getScreenCTM().inverse());
  const g = GRAPH;
  const plotWidth = g.width - g.marginLeft - g.marginRight;
  const frac = (svgPoint.x - g.marginLeft) / plotWidth;
  const step = Math.round(frac * (data.steps.length - 1));
  pausePlayback();
  seekToStep(step);
}

el.picker.addEventListener("change", () => loadPair(el.picker.value));
el.playPause.addEventListener("click", () => (playing ? pausePlayback() : startPlayback()));
el.scrubber.addEventListener("input", () => {
  pausePlayback();
  seekToStep(parseInt(el.scrubber.value, 10));
});
el.graph.addEventListener("click", graphClickToStep);

// --- Shared "processing" flow for both the upload form (POST /process) and
// the mark-attempt-end form (POST /realign): disable inputs, show a live
// elapsed-time counter, then on success load the resulting pair straight
// into the viewer via loadPair() - no page reload needed. On error, show
// the failing step name and its stderr rather than a generic message. ---

function setFormStatus(statusEl, message, kind) {
  statusEl.hidden = false;
  statusEl.textContent = message;
  statusEl.className = "upload-status" + (kind ? ` upload-${kind}` : "");
}

async function runWithProcessingUI({ inputs, submitBtn, idleLabel, statusEl, sendRequest, onSuccess }) {
  for (const input of inputs) input.disabled = true;
  submitBtn.disabled = true;
  submitBtn.textContent = "Processing...";

  const startTime = Date.now();
  const tick = () => {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    setFormStatus(statusEl, `Processing - this can take a few minutes. Elapsed: ${elapsed}s`);
  };
  tick();
  const timerId = setInterval(tick, 500);

  const reEnable = () => {
    clearInterval(timerId);
    for (const input of inputs) input.disabled = false;
    submitBtn.disabled = false;
    submitBtn.textContent = idleLabel;
  };

  let res;
  try {
    res = await sendRequest();
  } catch (err) {
    reEnable();
    setFormStatus(statusEl, `Request failed: ${err.message}`, "error");
    return;
  }

  let body;
  try {
    body = await res.json();
  } catch {
    body = { error: `Server returned a non-JSON response (status ${res.status})` };
  }

  if (!res.ok) {
    reEnable();
    const step = body.step || "unknown step";
    const detail = body.error || "unknown error";
    const stderr = body.stderr ? `\n\n${body.stderr}` : "";
    setFormStatus(statusEl, `Failed at ${step}: ${detail}${stderr}`, "error");
    return;
  }

  setFormStatus(statusEl, `Done: ${body.pair_name}`, "success");
  await onSuccess(body);
  reEnable();
}

el.uploadForm.addEventListener("submit", async (evt) => {
  evt.preventDefault();

  const fileA = el.fileA.files[0];
  const fileB = el.fileB.files[0];
  if (!fileA || !fileB) return;

  const formData = new FormData();
  formData.append("video_a", fileA);
  formData.append("video_b", fileB);

  await runWithProcessingUI({
    inputs: [el.fileA, el.fileB],
    submitBtn: el.uploadSubmit,
    idleLabel: "Process",
    statusEl: el.uploadStatus,
    sendRequest: () => fetch(PROCESS_URL, { method: "POST", body: formData }),
    onSuccess: async (body) => {
      el.uploadForm.reset();
      await loadPairsManifest();
      el.picker.value = body.data_path;
      await loadPair(body.data_path);
    },
  });
});

el.realignForm.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  if (!data) return;

  const payload = { name_a: data.label_a, name_b: data.label_b };
  if (el.endEventA.value !== "") payload.end_event_a = parseFloat(el.endEventA.value);
  if (el.endEventB.value !== "") payload.end_event_b = parseFloat(el.endEventB.value);

  await runWithProcessingUI({
    inputs: [el.endEventA, el.endEventB],
    submitBtn: el.realignSubmit,
    idleLabel: "Re-align",
    statusEl: el.realignStatus,
    sendRequest: () =>
      fetch(REALIGN_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: async (body) => {
      await loadPairsManifest();
      el.picker.value = body.data_path;
      await loadPair(body.data_path);
    },
  });
});

async function init() {
  await loadPairsManifest();
  if (!pairsManifest.length) {
    el.subtitle.textContent = "No processed attempt pairs found. Run build_viewer_data.py first.";
    return;
  }
  const requested = new URLSearchParams(location.search).get("pair");
  const match = pairsManifest.find((p) => p.name === requested);
  const initial = match ? match.data_path : pairsManifest[0].data_path;
  el.picker.value = initial;
  await loadPair(initial);
}

init();
