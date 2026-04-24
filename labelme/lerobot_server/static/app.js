"use strict";

/* ────────────────────────────────────────────────────────────────
   LabelVLA · Remote — browser UI that mirrors the desktop labelvla.
   Single-file vanilla JS, no dependencies.
   ──────────────────────────────────────────────────────────────── */

const SEG_COLORS = [
  "#3aa7ff", "#ff9a3c", "#6bd9a6", "#c179ff",
  "#ff5a5a", "#ffd166", "#5ac8e8", "#b3e66b",
];
const JOINT_COLORS = [
  "#3aa7ff", "#ff9a3c", "#6bd9a6", "#c179ff",
  "#ff5a5a", "#ffd166", "#5ac8e8", "#b3e66b",
  "#ff7ac9", "#7cffd1", "#ffa67a", "#a8b4ff",
  "#e8ff7a", "#d67aff",
];

const app = {
  // Dataset-wide
  dataset: null,          // {path, fps, num_episodes, episodes, camera_keys, joint_names}
  cameras: { head: null, left: null, right: null },

  // Per-episode
  episode_idx: 0,
  episode_length: 0,
  states: null,           // {joint_names, data: [[...], ...]}
  segments: [],           // [{start_frame, end_frame, text, bboxes:[{id,x,y,width,height,label,keypoints:[{frame,cx,cy}]}]}]

  // View state
  current_frame: 0,
  visible_joints: null,   // Set<number>

  // Selection
  selected_segment_idx: -1,
  selected_bbox_id: null,

  // Interaction state
  tracking_mode: false,
  dragging_bbox: null,    // {startX, startY, curX, curY} in image coords
  joints_panel_open: false,

  // Dirty flag
  dirty: false,

  // Pending label dialog
  _label_resolve: null,
  _segment_dialog_resolve: null,

  // Head image natural size (cached)
  head_natural: { w: 0, h: 0 },
};

/* ── API helpers ──────────────────────────────────────────────── */
const API = {
  async openDataset(path) {
    const url = path
      ? `/api/dataset?path=${encodeURIComponent(path)}`
      : `/api/dataset`;
    const r = await fetch(url);
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || "Failed to load dataset");
    }
    return r.json();
  },
  async states(episodeIdx) {
    const r = await fetch(`/api/episode/${episodeIdx}/states`);
    if (!r.ok) throw new Error("Failed to load states");
    return r.json();
  },
  frameURL(episodeIdx, frameIdx, camera) {
    return (
      `/api/episode/${episodeIdx}/frame/${frameIdx}` +
      `?camera=${encodeURIComponent(camera)}`
    );
  },
  async segments(episodeIdx) {
    const r = await fetch(`/api/episode/${episodeIdx}/segments`);
    if (!r.ok) throw new Error("Failed to load segments");
    return r.json();
  },
  async saveSegments(episodeIdx, segments) {
    const r = await fetch(`/api/episode/${episodeIdx}/segments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ segments }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || "Save failed");
    }
    return r.json();
  },
};

/* ── Camera classification ────────────────────────────────────── */
function classifyCameras(keys) {
  const out = { head: null, left: null, right: null };
  const rest = [];
  for (const k of keys) {
    const low = k.toLowerCase();
    if (!out.head && /(head|top|front|main|cam_high|ego)/.test(low)) {
      out.head = k;
    } else if (!out.left && /left/.test(low)) {
      out.left = k;
    } else if (!out.right && /right/.test(low)) {
      out.right = k;
    } else {
      rest.push(k);
    }
  }
  if (!out.head) out.head = keys[0] || null;
  if (!out.left) out.left = rest.shift() || null;
  if (!out.right) out.right = rest.shift() || null;
  return out;
}

/* ── Status line ──────────────────────────────────────────────── */
function setStatus(msg, kind) {
  const el = document.getElementById("status-line");
  el.textContent = msg || "";
  el.className = "status-line" + (kind ? ` ${kind}` : "");
}

/* ── Welcome screen ───────────────────────────────────────────── */
async function init() {
  // Try to auto-load any pre-configured dataset
  try {
    const ds = await API.openDataset(null);
    onDatasetLoaded(ds);
  } catch {
    showWelcome();
  }
  wireWelcome();
  wireWorkspace();
  wireDialogs();
  wireKeys();
  window.addEventListener("resize", onResize);
  window.addEventListener("beforeunload", (e) => {
    if (app.dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

function showWelcome() {
  document.getElementById("welcome").classList.remove("hidden");
  document.getElementById("workspace").classList.add("hidden");
}

function wireWelcome() {
  const pathInput = document.getElementById("dataset-path");
  const errLine = document.getElementById("welcome-error");
  const btn = document.getElementById("open-dataset-btn");

  async function attemptOpen() {
    errLine.classList.add("hidden");
    btn.disabled = true;
    try {
      const ds = await API.openDataset(pathInput.value.trim());
      onDatasetLoaded(ds);
    } catch (e) {
      errLine.textContent = e.message;
      errLine.classList.remove("hidden");
    } finally {
      btn.disabled = false;
    }
  }
  btn.addEventListener("click", attemptOpen);
  pathInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") attemptOpen();
  });
}

function onDatasetLoaded(ds) {
  app.dataset = ds;
  app.cameras = classifyCameras(ds.camera_keys);
  document.getElementById("welcome").classList.add("hidden");
  document.getElementById("workspace").classList.remove("hidden");
  document.getElementById("dataset-path-display").textContent = ds.path;

  const sel = document.getElementById("episode-select");
  sel.innerHTML = "";
  for (const ep of ds.episodes) {
    const opt = document.createElement("option");
    opt.value = String(ep.index);
    opt.textContent = `Episode ${ep.index} (${ep.length} frames)`;
    sel.appendChild(opt);
  }

  // Wrist camera labels
  const leftLbl = document.getElementById("left-wrist-label");
  const rightLbl = document.getElementById("right-wrist-label");
  const headLbl = document.getElementById("head-camera-label");
  if (app.cameras.head) headLbl.textContent = shortCam(app.cameras.head);
  if (app.cameras.left) leftLbl.textContent = shortCam(app.cameras.left);
  else leftLbl.textContent = "left wrist (n/a)";
  if (app.cameras.right) rightLbl.textContent = shortCam(app.cameras.right);
  else rightLbl.textContent = "right wrist (n/a)";

  loadEpisode(0);
}

function shortCam(k) {
  return k.replace(/^observation\.images?\./, "");
}

/* ── Workspace wiring ─────────────────────────────────────────── */
function wireWorkspace() {
  document
    .getElementById("episode-select")
    .addEventListener("change", (e) => {
      loadEpisode(parseInt(e.target.value, 10));
    });

  document.getElementById("save-btn").addEventListener("click", save);
  document.getElementById("joints-toggle-btn").addEventListener("click", () => {
    app.joints_panel_open = !app.joints_panel_open;
    document
      .getElementById("joint-checkboxes")
      .classList.toggle("hidden", !app.joints_panel_open);
  });

  document
    .getElementById("joints-all-btn")
    .addEventListener("click", () => setAllJointsVisible(true));
  document
    .getElementById("joints-none-btn")
    .addEventListener("click", () => setAllJointsVisible(false));

  document
    .getElementById("frame-slider")
    .addEventListener("input", (e) => {
      seek(parseInt(e.target.value, 10));
    });

  document
    .getElementById("prev-frame-btn")
    .addEventListener("click", () => seek(app.current_frame - 1));
  document
    .getElementById("next-frame-btn")
    .addEventListener("click", () => seek(app.current_frame + 1));

  document
    .getElementById("add-segment-btn")
    .addEventListener("click", () => onAddSegment(false));
  document
    .getElementById("add-segment-here-btn")
    .addEventListener("click", () => onAddSegment(true));

  document.getElementById("track-btn").addEventListener("click", toggleTracking);
  document.getElementById("clear-path-btn").addEventListener("click", clearPath);
  document
    .getElementById("delete-bbox-btn")
    .addEventListener("click", deleteSelectedBBox);

  const headImg = document.getElementById("head-image");
  headImg.addEventListener("load", () => {
    app.head_natural.w = headImg.naturalWidth;
    app.head_natural.h = headImg.naturalHeight;
    drawHeadCanvas();
  });

  const headCanvas = document.getElementById("head-canvas");
  headCanvas.addEventListener("mousedown", onHeadMouseDown);
  headCanvas.addEventListener("mousemove", onHeadMouseMove);
  window.addEventListener("mouseup", onHeadMouseUp);
}

function wireDialogs() {
  // Segment dialog
  const segDlg = document.getElementById("segment-dialog");
  document
    .getElementById("seg-cancel-btn")
    .addEventListener("click", () => closeSegmentDialog(null));
  document
    .getElementById("seg-confirm-btn")
    .addEventListener("click", confirmSegmentDialog);
  segDlg.addEventListener("click", (e) => {
    if (e.target === segDlg) closeSegmentDialog(null);
  });

  // Label dialog
  const lblDlg = document.getElementById("label-dialog");
  document
    .getElementById("label-cancel-btn")
    .addEventListener("click", () => closeLabelDialog(null));
  document
    .getElementById("label-confirm-btn")
    .addEventListener("click", () => {
      const v = document.getElementById("label-input").value.trim();
      closeLabelDialog(v || null);
    });
  document.getElementById("label-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const v = e.target.value.trim();
      closeLabelDialog(v || null);
    } else if (e.key === "Escape") {
      closeLabelDialog(null);
    }
  });
  lblDlg.addEventListener("click", (e) => {
    if (e.target === lblDlg) closeLabelDialog(null);
  });
}

function wireKeys() {
  window.addEventListener("keydown", (e) => {
    // Skip when typing in inputs/textareas
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      save();
      return;
    }
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      seek(app.current_frame - 1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      seek(app.current_frame + 1);
    } else if (e.key === "Escape") {
      if (app.tracking_mode) toggleTracking();
    }
  });
}

function onResize() {
  drawJointCanvas();
  drawHeadCanvas();
  drawSegmentBar();
}

/* ── Episode loading ──────────────────────────────────────────── */
async function loadEpisode(idx) {
  if (app.dirty) {
    await save();
  }
  app.episode_idx = idx;
  app.current_frame = 0;
  app.selected_segment_idx = -1;
  app.selected_bbox_id = null;
  app.tracking_mode = false;
  document.getElementById("track-btn").classList.remove("active");
  document.getElementById("head-canvas").classList.remove("tracking");
  document.getElementById("episode-select").value = String(idx);

  const ep = app.dataset.episodes.find((e) => e.index === idx);
  app.episode_length = ep ? ep.length : 0;

  const slider = document.getElementById("frame-slider");
  slider.min = 0;
  slider.max = Math.max(0, app.episode_length - 1);
  slider.value = 0;

  setStatus("Loading episode…");
  try {
    const [states, segs] = await Promise.all([
      API.states(idx),
      API.segments(idx),
    ]);
    app.states = states;
    if (app.visible_joints === null) {
      app.visible_joints = new Set(states.joint_names.map((_, i) => i));
    }
    app.segments = segs.segments || [];
    app.dirty = false;
    renderJointCheckboxes();
    renderSegmentList();
    renderBBoxList();
    drawJointCanvas();
    drawSegmentBar();
    updateTimelineInfo();
    await seek(0);
    setStatus("Ready", "ok");
  } catch (e) {
    console.error(e);
    setStatus(e.message, "error");
  }
}

async function seek(frame) {
  frame = Math.max(0, Math.min(app.episode_length - 1, frame));
  app.current_frame = frame;
  document.getElementById("frame-slider").value = String(frame);
  document.getElementById("frame-counter").textContent =
    `${frame} / ${app.episode_length - 1}`;

  // Update camera images — all three in parallel
  const urlHead = app.cameras.head
    ? API.frameURL(app.episode_idx, frame, app.cameras.head)
    : "";
  const urlLeft = app.cameras.left
    ? API.frameURL(app.episode_idx, frame, app.cameras.left)
    : "";
  const urlRight = app.cameras.right
    ? API.frameURL(app.episode_idx, frame, app.cameras.right)
    : "";
  document.getElementById("head-image").src = urlHead;
  document.getElementById("left-wrist-image").src = urlLeft;
  document.getElementById("right-wrist-image").src = urlRight;

  drawJointCanvas();
  drawSegmentBar();
  drawHeadCanvas();

  // Auto-select segment at current frame if selection is invalid
  const cur = app.segments[app.selected_segment_idx];
  if (!cur || frame < cur.start_frame || frame > cur.end_frame) {
    const idx = app.segments.findIndex(
      (s) => s.start_frame <= frame && frame <= s.end_frame,
    );
    if (idx !== -1 && idx !== app.selected_segment_idx) {
      setSelectedSegment(idx);
    }
  }
}

/* ── Joint checkboxes ─────────────────────────────────────────── */
function setAllJointsVisible(v) {
  const n = app.states.joint_names.length;
  app.visible_joints = v ? new Set(Array.from({ length: n }, (_, i) => i)) : new Set();
  renderJointCheckboxes();
  drawJointCanvas();
}

function renderJointCheckboxes() {
  const list = document.getElementById("joint-checkboxes-list");
  list.innerHTML = "";
  app.states.joint_names.forEach((name, i) => {
    const row = document.createElement("label");
    row.className = "joint-checkbox";
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = JOINT_COLORS[i % JOINT_COLORS.length];
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = app.visible_joints.has(i);
    cb.addEventListener("change", () => {
      if (cb.checked) app.visible_joints.add(i);
      else app.visible_joints.delete(i);
      drawJointCanvas();
    });
    const lbl = document.createElement("span");
    lbl.textContent = name;
    row.append(cb, swatch, lbl);
    list.appendChild(row);
  });
  document.getElementById("joint-info").textContent =
    `${app.visible_joints.size} / ${app.states.joint_names.length} joints visible`;
}

/* ── Canvas sizing ────────────────────────────────────────────── */
function sizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.floor(rect.width * dpr));
  const h = Math.max(1, Math.floor(rect.height * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width: rect.width, height: rect.height };
}

/* ── Joint curves ─────────────────────────────────────────────── */
function drawJointCanvas() {
  const canvas = document.getElementById("joint-canvas");
  const { ctx, width, height } = sizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);

  if (!app.states) return;

  const data = app.states.data;
  const names = app.states.joint_names;
  const n = data.length;
  if (n === 0) return;

  const padL = 40, padR = 10, padT = 10, padB = 18;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  // Compute y-range across visible joints
  let minV = Infinity, maxV = -Infinity;
  for (let j = 0; j < names.length; j++) {
    if (!app.visible_joints.has(j)) continue;
    for (let i = 0; i < n; i++) {
      const v = data[i][j];
      if (v < minV) minV = v;
      if (v > maxV) maxV = v;
    }
  }
  if (!isFinite(minV)) { minV = -1; maxV = 1; }
  if (minV === maxV) { minV -= 1; maxV += 1; }
  const pad = (maxV - minV) * 0.08;
  minV -= pad; maxV += pad;

  // Background segment bands
  for (let si = 0; si < app.segments.length; si++) {
    const s = app.segments[si];
    const x0 = padL + (s.start_frame / Math.max(1, n - 1)) * plotW;
    const x1 = padL + (s.end_frame / Math.max(1, n - 1)) * plotW;
    ctx.fillStyle = segFill(si, si === app.selected_segment_idx ? 0.28 : 0.14);
    ctx.fillRect(x0, padT, x1 - x0, plotH);
    // Segment label
    if (x1 - x0 > 36) {
      ctx.fillStyle = "rgba(255,255,255,0.5)";
      ctx.font = "10px ui-monospace, Menlo, monospace";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(s.text || `seg ${si}`, x0 + 4, padT + 2);
    }
  }

  // Axes frame
  ctx.strokeStyle = "#2e3444";
  ctx.lineWidth = 1;
  ctx.strokeRect(padL, padT, plotW, plotH);

  // Y tick marks
  ctx.fillStyle = "#6e7689";
  ctx.font = "10px ui-monospace, Menlo, monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const ticks = 3;
  for (let t = 0; t <= ticks; t++) {
    const v = maxV - ((maxV - minV) * t) / ticks;
    const y = padT + (plotH * t) / ticks;
    ctx.fillText(v.toFixed(2), padL - 4, y);
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + plotW, y);
    ctx.stroke();
  }

  // Curves
  for (let j = 0; j < names.length; j++) {
    if (!app.visible_joints.has(j)) continue;
    ctx.strokeStyle = JOINT_COLORS[j % JOINT_COLORS.length];
    ctx.lineWidth = 1.25;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const x = padL + (i / Math.max(1, n - 1)) * plotW;
      const y =
        padT + plotH - ((data[i][j] - minV) / (maxV - minV)) * plotH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Current frame indicator
  const curX =
    padL + (app.current_frame / Math.max(1, n - 1)) * plotW;
  ctx.strokeStyle = "rgba(255,255,255,0.5)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(curX, padT);
  ctx.lineTo(curX, padT + plotH);
  ctx.stroke();
  ctx.fillStyle = "#3aa7ff";
  ctx.beginPath();
  ctx.arc(curX, padT + plotH, 3, 0, Math.PI * 2);
  ctx.fill();

  // Click-to-seek (rebind each render to have current state closure)
  canvas.onclick = (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    if (mx < padL || mx > padL + plotW) return;
    const frame = Math.round(((mx - padL) / plotW) * (n - 1));
    seek(frame);
  };
}

function segFill(idx, alpha) {
  const hex = SEG_COLORS[idx % SEG_COLORS.length];
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/* ── Timeline segment bar ─────────────────────────────────────── */
function drawSegmentBar() {
  const canvas = document.getElementById("segment-bar");
  const { ctx, width, height } = sizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const n = Math.max(1, app.episode_length - 1);

  // Base track
  ctx.fillStyle = "#2e3444";
  ctx.fillRect(0, height - 4, width, 4);

  // Segment blocks
  for (let i = 0; i < app.segments.length; i++) {
    const s = app.segments[i];
    const x0 = (s.start_frame / n) * width;
    const x1 = (s.end_frame / n) * width;
    ctx.fillStyle = SEG_COLORS[i % SEG_COLORS.length];
    ctx.globalAlpha = i === app.selected_segment_idx ? 1.0 : 0.7;
    ctx.fillRect(x0, 2, Math.max(2, x1 - x0), height - 8);
  }
  ctx.globalAlpha = 1;
}

function updateTimelineInfo() {
  document.getElementById("timeline-info").textContent =
    `episode ${app.episode_idx} · ${app.episode_length} frames @ ${app.dataset.fps} fps`;
}

/* ── Head camera canvas ───────────────────────────────────────── */
function getHeadRect() {
  const container = document.getElementById("head-viewport");
  const cw = container.clientWidth;
  const ch = container.clientHeight;
  const iw = app.head_natural.w;
  const ih = app.head_natural.h;
  if (!iw || !ih) return null;
  const scale = Math.min(cw / iw, ch / ih);
  const w = iw * scale;
  const h = ih * scale;
  return {
    x: (cw - w) / 2,
    y: (ch - h) / 2,
    w,
    h,
    scale,
    imageW: iw,
    imageH: ih,
  };
}

function drawHeadCanvas() {
  const canvas = document.getElementById("head-canvas");
  const { ctx, width, height } = sizeCanvas(canvas);
  ctx.clearRect(0, 0, width, height);

  const rect = getHeadRect();
  if (!rect) return;

  const seg = app.segments[app.selected_segment_idx];
  const frame = app.current_frame;

  // Draw all bboxes in ALL segments that contain current frame
  for (let si = 0; si < app.segments.length; si++) {
    const s = app.segments[si];
    if (frame < s.start_frame || frame > s.end_frame) continue;
    for (const b of s.bboxes) {
      const { cx, cy } = interpolateCenter(b, frame);
      const x = cx - b.width / 2;
      const y = cy - b.height / 2;
      const selected =
        si === app.selected_segment_idx && b.id === app.selected_bbox_id;
      drawBBox(ctx, rect, x, y, b.width, b.height, b, selected);
      if (b.keypoints && b.keypoints.length > 1) {
        drawMotionPath(ctx, rect, b);
      }
    }
  }

  // In-progress drag
  if (app.dragging_bbox) {
    const d = app.dragging_bbox;
    const x = Math.min(d.startX, d.curX);
    const y = Math.min(d.startY, d.curY);
    const w = Math.abs(d.curX - d.startX);
    const h = Math.abs(d.curY - d.startY);
    const p0 = imgToCanvas(x, y, rect);
    ctx.strokeStyle = "#3aa7ff";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(p0.x, p0.y, w * rect.scale, h * rect.scale);
    ctx.setLineDash([]);
  }
}

function drawBBox(ctx, rect, x, y, w, h, bbox, selected) {
  const p = imgToCanvas(x, y, rect);
  const ww = w * rect.scale;
  const hh = h * rect.scale;
  const moving = bbox.keypoints && bbox.keypoints.length > 0;

  let color;
  if (app.tracking_mode && selected) color = "#ffd166";
  else if (selected) color = "#3aa7ff";
  else if (moving) color = "#6bd9a6";
  else color = "#c179ff";

  ctx.strokeStyle = color;
  ctx.lineWidth = selected ? 2.5 : 1.5;
  ctx.strokeRect(p.x, p.y, ww, hh);

  // Corner indicators
  const cornerLen = 6;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(p.x, p.y + cornerLen); ctx.lineTo(p.x, p.y); ctx.lineTo(p.x + cornerLen, p.y);
  ctx.moveTo(p.x + ww - cornerLen, p.y); ctx.lineTo(p.x + ww, p.y); ctx.lineTo(p.x + ww, p.y + cornerLen);
  ctx.moveTo(p.x + ww, p.y + hh - cornerLen); ctx.lineTo(p.x + ww, p.y + hh); ctx.lineTo(p.x + ww - cornerLen, p.y + hh);
  ctx.moveTo(p.x + cornerLen, p.y + hh); ctx.lineTo(p.x, p.y + hh); ctx.lineTo(p.x, p.y + hh - cornerLen);
  ctx.stroke();

  // Label
  const tag = `[${bbox.id}] ${bbox.label}` +
    (moving ? " · moving" : "") +
    (app.tracking_mode && selected ? " · tracking" : "");
  ctx.font = "11px ui-monospace, Menlo, monospace";
  const mw = ctx.measureText(tag).width;
  ctx.fillStyle = color;
  ctx.fillRect(p.x, p.y - 16, mw + 8, 14);
  ctx.fillStyle = "#0b0d13";
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.fillText(tag, p.x + 4, p.y - 9);
}

function drawMotionPath(ctx, rect, bbox) {
  const kps = bbox.keypoints.slice().sort((a, b) => a.frame - b.frame);
  ctx.strokeStyle = "rgba(255,90,90,0.7)";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  for (let i = 0; i < kps.length; i++) {
    const p = imgToCanvas(kps[i].cx, kps[i].cy, rect);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();
  ctx.setLineDash([]);

  // Draw keypoints
  for (const k of kps) {
    const p = imgToCanvas(k.cx, k.cy, rect);
    ctx.fillStyle = k.frame === app.current_frame ? "#ffd166" : "#ff5a5a";
    ctx.beginPath();
    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#0b0d13";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

let _pendingCounter = 0;
function pendingId() {
  _pendingCounter += 1;
  return `_pending_${Date.now()}_${_pendingCounter}`;
}

function imgToCanvas(x, y, rect) {
  return { x: rect.x + x * rect.scale, y: rect.y + y * rect.scale };
}
function canvasToImg(x, y, rect) {
  return { x: (x - rect.x) / rect.scale, y: (y - rect.y) / rect.scale };
}

function interpolateCenter(bbox, frame) {
  if (!bbox.keypoints || bbox.keypoints.length === 0) {
    return { cx: bbox.x + bbox.width / 2, cy: bbox.y + bbox.height / 2 };
  }
  const kps = bbox.keypoints.slice().sort((a, b) => a.frame - b.frame);
  if (frame <= kps[0].frame) return { cx: kps[0].cx, cy: kps[0].cy };
  if (frame >= kps[kps.length - 1].frame) {
    return { cx: kps[kps.length - 1].cx, cy: kps[kps.length - 1].cy };
  }
  for (let i = 0; i < kps.length - 1; i++) {
    if (kps[i].frame <= frame && frame <= kps[i + 1].frame) {
      const t = (frame - kps[i].frame) / (kps[i + 1].frame - kps[i].frame);
      return {
        cx: kps[i].cx + t * (kps[i + 1].cx - kps[i].cx),
        cy: kps[i].cy + t * (kps[i + 1].cy - kps[i].cy),
      };
    }
  }
  return { cx: bbox.x + bbox.width / 2, cy: bbox.y + bbox.height / 2 };
}

/* ── Head camera mouse handling ───────────────────────────────── */
function onHeadMouseDown(e) {
  const canvas = document.getElementById("head-canvas");
  const rect = getHeadRect();
  if (!rect) return;
  const r = canvas.getBoundingClientRect();
  const mx = e.clientX - r.left;
  const my = e.clientY - r.top;
  if (mx < rect.x || mx > rect.x + rect.w) return;
  if (my < rect.y || my > rect.y + rect.h) return;
  const img = canvasToImg(mx, my, rect);

  if (app.tracking_mode) {
    addKeypoint(img.x, img.y);
    return;
  }

  app.dragging_bbox = {
    startX: img.x,
    startY: img.y,
    curX: img.x,
    curY: img.y,
  };
}

function onHeadMouseMove(e) {
  if (!app.dragging_bbox) return;
  const canvas = document.getElementById("head-canvas");
  const rect = getHeadRect();
  if (!rect) return;
  const r = canvas.getBoundingClientRect();
  const mx = e.clientX - r.left;
  const my = e.clientY - r.top;
  const img = canvasToImg(mx, my, rect);
  // Clamp
  app.dragging_bbox.curX = Math.max(0, Math.min(rect.imageW, img.x));
  app.dragging_bbox.curY = Math.max(0, Math.min(rect.imageH, img.y));
  drawHeadCanvas();
}

async function onHeadMouseUp() {
  if (!app.dragging_bbox) return;
  const d = app.dragging_bbox;
  app.dragging_bbox = null;
  const w = Math.abs(d.curX - d.startX);
  const h = Math.abs(d.curY - d.startY);
  drawHeadCanvas();
  if (w < 4 || h < 4) return;

  // Determine target segment
  let segIdx = app.selected_segment_idx;
  const cur = app.segments[segIdx];
  if (!cur || app.current_frame < cur.start_frame || app.current_frame > cur.end_frame) {
    segIdx = app.segments.findIndex(
      (s) =>
        s.start_frame <= app.current_frame && app.current_frame <= s.end_frame,
    );
  }
  if (segIdx < 0) {
    setStatus("Draw bboxes inside a segment first", "warn");
    return;
  }

  const label = await promptLabel();
  if (!label) return;

  const x = Math.min(d.startX, d.curX);
  const y = Math.min(d.startY, d.curY);
  const newBox = {
    id: null, // server will allocate
    label,
    x, y, width: w, height: h,
    keypoints: [],
  };
  app.segments[segIdx].bboxes.push(newBox);
  setSelectedSegment(segIdx);
  // Client-side transient id; save() swaps for a server-allocated int.
  newBox.id = pendingId();
  app.selected_bbox_id = newBox.id;
  markDirty();
  renderBBoxList();
  drawHeadCanvas();
}

function addKeypoint(x, y) {
  const bbox = findSelectedBBox();
  if (!bbox) return;
  const seg = app.segments[app.selected_segment_idx];
  if (!seg) return;
  const frame = app.current_frame;
  if (frame < seg.start_frame || frame > seg.end_frame) {
    setStatus("Current frame is outside the selected segment", "warn");
    return;
  }
  const kps = bbox.keypoints || (bbox.keypoints = []);
  const existing = kps.findIndex((k) => k.frame === frame);
  const kp = { frame, cx: x, cy: y };
  if (existing >= 0) kps[existing] = kp;
  else kps.push(kp);
  kps.sort((a, b) => a.frame - b.frame);
  markDirty();
  drawHeadCanvas();
  renderBBoxList();
}

/* ── Segment + bbox panels ────────────────────────────────────── */
function renderSegmentList() {
  const ul = document.getElementById("segment-list");
  ul.innerHTML = "";
  app.segments.forEach((s, i) => {
    const li = document.createElement("li");
    li.className = "dock-item";
    if (i === app.selected_segment_idx) li.classList.add("selected");
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = `seg ${i}`;
    chip.style.background = segFill(i, 0.25);
    chip.style.color = SEG_COLORS[i % SEG_COLORS.length];
    const frames = document.createElement("span");
    frames.className = "frames";
    frames.textContent = `${s.start_frame}–${s.end_frame}`;
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = s.text || "(no text)";
    li.append(chip, frames, title);
    li.addEventListener("click", () => {
      setSelectedSegment(i);
      seek(s.start_frame);
    });
    li.addEventListener("dblclick", () => editSegment(i));
    // Right-click to delete
    li.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      if (confirm(`Delete segment ${i}?`)) {
        app.segments.splice(i, 1);
        if (app.selected_segment_idx === i) setSelectedSegment(-1);
        markDirty();
        renderSegmentList();
        renderBBoxList();
        drawSegmentBar();
        drawJointCanvas();
        drawHeadCanvas();
      }
    });
    ul.appendChild(li);
  });
  if (app.segments.length === 0) {
    const li = document.createElement("li");
    li.className = "dock-item";
    li.style.color = "var(--muted)";
    li.style.justifyContent = "center";
    li.textContent = "no segments";
    ul.appendChild(li);
  }
}

function renderBBoxList() {
  const ul = document.getElementById("bbox-list");
  ul.innerHTML = "";
  const seg = app.segments[app.selected_segment_idx];
  if (!seg) {
    const li = document.createElement("li");
    li.className = "dock-item";
    li.style.color = "var(--muted)";
    li.style.justifyContent = "center";
    li.textContent = "select a segment";
    ul.appendChild(li);
  } else {
    for (const b of seg.bboxes) {
      const li = document.createElement("li");
      li.className = "dock-item";
      if (b.id === app.selected_bbox_id) li.classList.add("selected");
      const chip = document.createElement("span");
      chip.className = "chip";
      if (b.keypoints && b.keypoints.length > 0) chip.classList.add("moving");
      chip.textContent = `id:${b.id}`;
      const title = document.createElement("span");
      title.className = "title";
      title.textContent = b.label;
      const meta = document.createElement("span");
      meta.className = "frames";
      meta.textContent = `${Math.round(b.width)}×${Math.round(b.height)}` +
        (b.keypoints && b.keypoints.length
          ? ` · ${b.keypoints.length} kp`
          : "");
      li.append(chip, title, meta);
      li.addEventListener("click", () => {
        app.selected_bbox_id = b.id;
        updateBBoxButtons();
        renderBBoxList();
        drawHeadCanvas();
      });
      ul.appendChild(li);
    }
    if (seg.bboxes.length === 0) {
      const li = document.createElement("li");
      li.className = "dock-item";
      li.style.color = "var(--muted)";
      li.style.justifyContent = "center";
      li.textContent = "draw a bbox on the head camera";
      ul.appendChild(li);
    }
  }
  updateBBoxButtons();
}

function setSelectedSegment(i) {
  app.selected_segment_idx = i;
  app.selected_bbox_id = null;
  if (app.tracking_mode) toggleTracking();
  renderSegmentList();
  renderBBoxList();
  drawJointCanvas();
  drawSegmentBar();
  drawHeadCanvas();
}

function updateBBoxButtons() {
  const b = findSelectedBBox();
  document.getElementById("track-btn").disabled = !b;
  document.getElementById("clear-path-btn").disabled =
    !b || !b.keypoints || b.keypoints.length === 0;
  document.getElementById("delete-bbox-btn").disabled = !b;
}

function findSelectedBBox() {
  const seg = app.segments[app.selected_segment_idx];
  if (!seg) return null;
  return seg.bboxes.find((b) => b.id === app.selected_bbox_id) || null;
}

/* ── Segment add/edit ─────────────────────────────────────────── */
async function onAddSegment(atCurrent) {
  const result = await openSegmentDialog({
    start_frame: atCurrent ? app.current_frame : 0,
    end_frame: atCurrent
      ? Math.min(app.current_frame + 30, app.episode_length - 1)
      : Math.min(30, app.episode_length - 1),
    text: "",
  });
  if (!result) return;
  app.segments.push({
    start_frame: result.start_frame,
    end_frame: result.end_frame,
    text: result.text,
    bboxes: [],
  });
  // Keep segments sorted by start_frame
  app.segments.sort((a, b) => a.start_frame - b.start_frame);
  const newIdx = app.segments.findIndex(
    (s) =>
      s.start_frame === result.start_frame &&
      s.end_frame === result.end_frame,
  );
  setSelectedSegment(newIdx);
  markDirty();
}

async function editSegment(i) {
  const s = app.segments[i];
  const result = await openSegmentDialog(s);
  if (!result) return;
  s.start_frame = result.start_frame;
  s.end_frame = result.end_frame;
  s.text = result.text;
  app.segments.sort((a, b) => a.start_frame - b.start_frame);
  markDirty();
  renderSegmentList();
  drawSegmentBar();
  drawJointCanvas();
  drawHeadCanvas();
}

function openSegmentDialog(initial) {
  return new Promise((resolve) => {
    const dlg = document.getElementById("segment-dialog");
    document.getElementById("segment-dialog-title").textContent =
      initial.start_frame !== undefined && initial.end_frame !== undefined &&
        initial.start_frame === initial.end_frame ? "Add Segment" : "Edit Segment";
    document.getElementById("seg-start").value = String(initial.start_frame || 0);
    document.getElementById("seg-end").value = String(initial.end_frame || 0);
    document.getElementById("seg-text").value = initial.text || "";
    const startIn = document.getElementById("seg-start");
    const endIn = document.getElementById("seg-end");
    startIn.max = String(app.episode_length - 1);
    endIn.max = String(app.episode_length - 1);
    dlg.classList.remove("hidden");
    setTimeout(() => document.getElementById("seg-text").focus(), 10);
    app._segment_dialog_resolve = resolve;
  });
}

function closeSegmentDialog(value) {
  document.getElementById("segment-dialog").classList.add("hidden");
  if (app._segment_dialog_resolve) {
    app._segment_dialog_resolve(value);
    app._segment_dialog_resolve = null;
  }
}

function confirmSegmentDialog() {
  const start = parseInt(document.getElementById("seg-start").value, 10);
  const end = parseInt(document.getElementById("seg-end").value, 10);
  const text = document.getElementById("seg-text").value.trim();
  if (!(start >= 0 && end >= start && end <= app.episode_length - 1)) {
    alert("Invalid frame range");
    return;
  }
  closeSegmentDialog({ start_frame: start, end_frame: end, text });
}

/* ── Label prompt ─────────────────────────────────────────────── */
function promptLabel() {
  return new Promise((resolve) => {
    const dlg = document.getElementById("label-dialog");
    document.getElementById("label-input").value = "";
    dlg.classList.remove("hidden");
    setTimeout(() => document.getElementById("label-input").focus(), 10);
    app._label_resolve = resolve;
  });
}

function closeLabelDialog(value) {
  document.getElementById("label-dialog").classList.add("hidden");
  if (app._label_resolve) {
    app._label_resolve(value);
    app._label_resolve = null;
  }
}

/* ── Tracking ─────────────────────────────────────────────────── */
function toggleTracking() {
  const b = findSelectedBBox();
  if (!b && !app.tracking_mode) return;
  app.tracking_mode = !app.tracking_mode;
  document
    .getElementById("track-btn")
    .classList.toggle("active", app.tracking_mode);
  document
    .getElementById("head-canvas")
    .classList.toggle("tracking", app.tracking_mode);
  setStatus(
    app.tracking_mode
      ? "Tracking: click the object center across frames (Esc to exit)"
      : "",
    app.tracking_mode ? "warn" : "",
  );
  drawHeadCanvas();
}

function clearPath() {
  const b = findSelectedBBox();
  if (!b) return;
  b.keypoints = [];
  markDirty();
  drawHeadCanvas();
  renderBBoxList();
}

function deleteSelectedBBox() {
  const seg = app.segments[app.selected_segment_idx];
  if (!seg) return;
  const i = seg.bboxes.findIndex((b) => b.id === app.selected_bbox_id);
  if (i < 0) return;
  seg.bboxes.splice(i, 1);
  app.selected_bbox_id = null;
  if (app.tracking_mode) toggleTracking();
  markDirty();
  renderBBoxList();
  drawHeadCanvas();
}

/* ── Save ─────────────────────────────────────────────────────── */
function markDirty() {
  app.dirty = true;
  setStatus("● Unsaved changes", "warn");
}

async function save() {
  setStatus("Saving…");
  // Normalize: strip transient string ids so server allocates int ids
  const payload = app.segments.map((s) => ({
    start_frame: s.start_frame,
    end_frame: s.end_frame,
    text: s.text,
    bboxes: s.bboxes.map((b) => ({
      id: typeof b.id === "number" ? b.id : null,
      label: b.label,
      x: b.x,
      y: b.y,
      width: b.width,
      height: b.height,
      keypoints: b.keypoints || [],
    })),
  }));
  try {
    const result = await API.saveSegments(app.episode_idx, payload);
    // Preserve UI selection across id reassignment by label + start frame
    const prevSel =
      app.selected_segment_idx >= 0
        ? app.segments[app.selected_segment_idx]
        : null;
    app.segments = result.segments || [];
    if (prevSel) {
      const ni = app.segments.findIndex(
        (s) =>
          s.start_frame === prevSel.start_frame &&
          s.end_frame === prevSel.end_frame,
      );
      app.selected_segment_idx = ni;
    }
    app.selected_bbox_id = null;
    app.dirty = false;
    setStatus("Saved", "ok");
    renderSegmentList();
    renderBBoxList();
    drawSegmentBar();
    drawJointCanvas();
    drawHeadCanvas();
  } catch (e) {
    console.error(e);
    setStatus(e.message, "error");
  }
}

/* ── Boot ─────────────────────────────────────────────────────── */
window.addEventListener("DOMContentLoaded", init);
