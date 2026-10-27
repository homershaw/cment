// Batch Plant SCADA front end. Plain JS, no external libraries (the plant network may be offline).
"use strict";

const BIN_CAP = 40000, SILO_CAP = 25000;   // kg; the program's refill values (OB1 network 7)
const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];
const S = { meta: null, tags: {}, snap: null, user: null, page: "overview", trendKeys: [], trendRange: 3600, trendTable: false };

const $ = (sel, el = document) => el.querySelector(sel);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const V = k => S.snap?.values?.[k];
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

async function api(path, opts = {}) {
  const init = { headers: {}, ...opts };
  if (opts.body !== undefined) { init.method = init.method || "POST"; init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  const r = await fetch(path, init);
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(data?.detail || r.statusText);
  return data;
}

function fmt(key, v = V(key)) {
  const t = S.tags[key];
  if (v === undefined || v === null) return "–";
  if (typeof v === "boolean") return v ? "ON" : "OFF";
  const d = t ? t.decimals : 1;
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}
const unit = key => S.tags[key]?.unit ? " " + S.tags[key].unit : "";
const num = (v, d = 0) => v === null || v === undefined ? "–" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const time = ts => ts ? new Date(ts * 1000).toLocaleString() : "";
const hms = s => { s = Math.max(0, Math.floor(s)); return `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
const stageName = n => S.meta?.stages?.[n] ?? `Stage ${n}`;

// ---------- live feed ----------
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = e => { S.snap = JSON.parse(e.data); render(); };
  ws.onclose = () => { S.snap = S.snap && { ...S.snap, connected: false, error: "SCADA server not reachable" }; render(); setTimeout(connect, 2000); };
}

// ---------- router ----------
function route() {
  S.page = (location.hash || "#overview").slice(1);
  document.querySelectorAll(".page").forEach(p => p.classList.toggle("active", p.id === "page-" + S.page));
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === "#" + S.page));
  ({ alarms: loadAlarmHistory, trends: loadTrends, batches: loadBatches, events: loadEvents })[S.page]?.();
  render();
}

function render() {
  if (!S.meta) return;
  renderHeader();
  ({ overview: renderOverview, control: renderControl, alarms: renderActiveAlarms, tags: renderTags })[S.page]?.();
}

// ---------- header ----------
function pill(id, cls, text) {
  const el = $("#" + id);
  el.querySelector(".dot").className = "dot " + (cls || "");
  el.querySelector("span:last-child").textContent = text;
}
function renderHeader() {
  const s = S.snap;
  if (!s) return;
  pill("plcPill", s.connected ? "good" : "critical", s.connected ? `PLC online · ${s.poll_ms} ms` : "PLC offline");
  $("#plcPill").title = s.error || `${S.meta.plc.host}:${S.meta.plc.port}`;
  const stage = V("batch.stage") ?? 0;
  const paused = V("batch.pause") || V("batch.pause_oot");
  pill("stagePill", paused ? "warning" : stage ? "good" : "", paused ? `${stageName(stage)} · PAUSED` : stageName(stage));
  const unacked = s.alarms.filter(a => !a.acked);
  pill("alarmPill", s.alarms.length ? "critical" : "", `${s.alarms.length} alarm${s.alarms.length === 1 ? "" : "s"}`);
  $("#alarmPill").classList.toggle("alarm", unacked.length > 0);
  $("#alarmPill .dot").classList.toggle("blink", unacked.length > 0);
  const top = unacked[0];
  $("#banner").classList.toggle("show", !!top);
  if (top) { $("#bannerText").textContent = `${time(top.raised)} · ${top.text}`; $("#bannerAck").dataset.id = top.id; }
}

// ---------- overview ----------
function chip(text, on, fault) { return `<span class="chip${fault ? " fault" : on ? " on" : ""}">${esc(text)}</span>`; }

function vesselCard(title, p, cap, extra) {
  const cur = V(`${p}.current`) ?? 0, req = V(`${p}.required`) ?? 0, batched = V(`${p}.batched`) ?? 0;
  const running = !!V(`${p}.run`), oot = V(`${p}.over_tol`) || V(`${p}.under_tol`);
  const pct = req > 0 ? Math.min(100, batched / req * 100) : 0;
  const stage = V("batch.stage");
  return `<div class="card vessel-card">
    <div class="title"><span>${esc(title)}</span>${running ? chip("Discharging", true) : ""}</div>
    <div class="vessel${running ? " active" : ""}" role="img" aria-label="${esc(title)} ${num(cur)} kg">
      <div class="fill" style="height:${Math.max(0, Math.min(100, cur / cap * 100))}%"></div>
      <div class="level"><div>${num(cur)}<small>kg</small></div></div>
    </div>
    ${stage && req > 0 ? `<div class="small row" style="justify-content:space-between"><span>${num(batched)} / ${num(req)} kg</span><span>${num(pct)}%</span></div>
    <div class="progress ${oot ? "bad" : V(`${p}.complete`) ? "done" : ""}"><div style="width:${pct}%"></div></div>` : `<div class="small muted">${V(`${p}.not_used`) ? "Not used" : "Idle"}</div>`}
    <div class="chips">${extra}${oot ? chip(V(`${p}.over_tol`) ? "Over tolerance" : "Under tolerance", false, true) : ""}${V(`${p}.no_flow`) ? chip("No flow", false, true) : ""}</div>
  </div>`;
}

function renderOverview() {
  const stage = V("batch.stage") ?? 0;
  $("#ovStage").textContent = S.snap?.connected ? stageName(stage) : "–";
  $("#ovQty").textContent = `${fmt("batch.quantity")} m³`;
  const b = S.snap?.batch;
  $("#ovElapsed").textContent = b ? hms(Date.now() / 1000 - b.started) : "–";
  $("#ovBatchNo").textContent = b ? `#${b.id}` : "–";
  $("#ovFlags").innerHTML = [
    chip("Ready to run", V("plant.ready"), S.snap?.connected && !V("plant.ready")),
    chip("Run batch", V("batch.run")),
    chip("Paused", false, V("batch.pause")),
    chip("Out of tolerance", false, V("batch.pause_oot")),
    chip("Klaxon", V("batch.klaxon")),
    chip("Manual (test) mode", false, V("plant.test_mode")),
    chip("E-stop healthy", V("plant.estop_healthy"), S.snap?.connected && !V("plant.estop_healthy")),
  ].join("");
  const eq = [["out.air_comp", "Air compressor"], ["out.hyd_pump", "Hydraulic pump"], ["out.water_pump", "Water pump"],
    ["out.main_conv", "Main conveyor"], ["out.dust1", "Dust collector 1"], ["out.dust2", "Dust collector 2"],
    ["out.horn", "Horn"], ["out.agg3_belt", "Agg 3 belt"]];
  $("#ovEquip").innerHTML = eq.map(([k, l]) => chip(l, V(k))).join("") +
    chip("Air pressure", V("plant.air_pressure_ok"), S.snap?.connected && !V("plant.air_pressure_ok")) +
    chip("Conveyor overload", false, V("plant.ol3"));

  let html = "";
  for (const n of [1, 2, 3]) {
    if (n === 3 && V("plant.third_bin_na")) continue;
    html += vesselCard(`Agg ${n}`, `bin${n}`, BIN_CAP,
      chip("Gate open", V(`out.agg${n}_open`)) + chip("Vibrator", V(`out.agg${n}_vib`)));
  }
  for (const n of [1, 2]) {
    html += vesselCard(`Silo ${n}`, `silo${n}`, SILO_CAP,
      chip("Auger", V(`out.auger${n}`)) + chip("Aerator", V(`out.silo${n}_aer`)) + chip("Vibrator", V(`out.silo${n}_vib`)));
  }
  const wReq = V("water.required") ?? 0, wDone = (V("water.head_level") ?? 0) + (V("water.tail_level") ?? 0);
  const wPct = wReq > 0 ? Math.min(100, wDone / wReq * 100) : 0;
  const wOot = V("water.over_tol") || V("water.under_tol");
  html += `<div class="card vessel-card">
    <div class="title"><span>Water</span>${V("out.water_pump") ? chip("Pumping", true) : ""}</div>
    <dl class="kv"><dt>Head water</dt><dd>${fmt("water.head_level")} L</dd><dt>Tail water</dt><dd>${fmt("water.tail_level")} L</dd>
    <dt>Required</dt><dd>${fmt("water.required")} L</dd><dt>Meter</dt><dd>${fmt("water.meter_read")} L</dd></dl>
    ${stage && wReq > 0 ? `<div class="progress ${wOot ? "bad" : V("water.tail_complete") ? "done" : ""}"><div style="width:${wPct}%"></div></div>` : ""}
    <div class="chips">${chip("Head", V("water.head_running"))}${chip("Tail", V("water.tail_running"))}${wOot ? chip("Out of tolerance", false, true) : ""}${V("water.no_flow") ? chip("No flow", false, true) : ""}</div>
  </div>`;
  $("#ovVessels").innerHTML = html;
  $("#ovConveyor").classList.toggle("run", !!V("plant.main_conv_running"));

  let adx = "";
  for (let n = 1; n <= 8; n++) {
    if (!V(`adx${n}.used`)) continue;
    const req = V(`adx${n}.required`) ?? 0, lvl = V(`adx${n}.level`) ?? 0;
    const pct = req > 0 ? Math.min(100, lvl / req * 100) : 0, oot = V(`adx${n}.over_tol`) || V(`adx${n}.under_tol`);
    adx += `<div class="card vessel-card"><div class="title"><span>Admix ${n}</span></div>
      ${req > 0 ? `<div class="small row" style="justify-content:space-between"><span>${num(lvl, 2)} / ${num(req, 2)} L</span><span>${num(pct)}%</span></div>`
        : `<div class="small muted">${stage ? "Not dosed in this batch" : "Idle"}</div>`}
      <div class="progress ${oot ? "bad" : V(`adx${n}.filled`) ? "done" : ""}"><div style="width:${pct}%"></div></div>
      <div class="chips">${chip("Fill", V(`out.adx${n}_fill`))}${chip("Discharge", V(`out.adx${n}_dis`))}${chip("Ready", V(`adx${n}.filled`))}${oot ? chip("Out of tolerance", false, true) : ""}</div></div>`;
  }
  $("#ovAdmix").innerHTML = adx;
}

// ---------- batch control ----------
function controlState() {
  const c = S.meta.control, live = S.snap?.connected, stage = V("batch.stage") ?? 0;
  const paused = V("batch.pause") || V("batch.pause_oot");
  const operator = S.user && ["operator", "admin"].includes(S.user.role);
  const reason = !c.enabled ? "Batch control is disabled in config.toml." : !live ? "No live PLC data." :
    !S.user ? "Log in as an operator to control batches." : !operator ? "Your account is view-only." : "";
  return {
    reason, stage, paused,
    start: !reason && stage === 0 && !V("batch.run") && V("plant.ready") && !V("plant.test_mode") && !V("batch.lockout"),
    pause: !reason && stage !== 0 && !V("batch.pause"),
    resume: !reason && paused && V("plant.estop_healthy"),
    abort: !reason && stage !== 0,
  };
}

function renderControl() {
  const st = controlState(), c = S.meta.control;
  $("#ctlNotice").innerHTML = st.reason ? `<div class="notice">${esc(st.reason)}</div>` :
    st.paused ? `<div class="notice error">Batch paused${V("batch.pause_oot") ? " — out of tolerance. Check the material, then Resume." : "."}</div>` :
    st.stage ? `<div class="notice ok">${esc(stageName(st.stage))} — batch running.</div>` : "";
  for (const k of ["start", "pause", "resume", "abort"]) $("#btn" + k[0].toUpperCase() + k.slice(1)).disabled = !st[k];
  $("#ctlQty").min = c.min_quantity; $("#ctlQty").max = c.max_quantity; $("#ctlQty").disabled = !st.start;
  $("#ctlHelp").textContent = `Quantity ${c.min_quantity}–${c.max_quantity} m³. Every action is recorded in the event log with your name.`;
  const il = [["Ready to run", V("plant.ready")], ["E-stop circuit healthy", V("plant.estop_healthy")],
    ["Air pressure OK", V("plant.air_pressure_ok")], ["Not in manual (test) mode", V("plant.test_mode") === false],
    ["PLC registered (no lockout)", V("batch.lockout") === false]];
  $("#ctlInterlocks").innerHTML = il.map(([l, ok]) => chip(l, ok, S.snap?.connected && !ok)).join("") +
    chip((V("batch.stage") ?? 0) === 0 ? "No batch running" : "Batch running", false);
  const mats = materialsNow();
  $("#ctlMaterials").innerHTML = materialTable(mats);
}

function materialsNow() {
  const out = [];
  for (const n of [1, 2, 3]) out.push([`Agg ${n}`, "kg", V(`bin${n}.required`), V(`bin${n}.batched`), V(`bin${n}.accuracy`), V(`bin${n}.complete`), V(`bin${n}.over_tol`) || V(`bin${n}.under_tol`), 0]);
  for (const n of [1, 2]) out.push([`Silo ${n}`, "kg", V(`silo${n}.required`), V(`silo${n}.batched`), V(`silo${n}.accuracy`), V(`silo${n}.complete`), V(`silo${n}.over_tol`) || V(`silo${n}.under_tol`), 0]);
  out.push(["Water", "L", V("water.required"), (V("water.head_level") ?? 0) + (V("water.tail_level") ?? 0), V("water.accuracy"), V("water.tail_complete"), V("water.over_tol") || V("water.under_tol"), 1]);
  for (let n = 1; n <= 8; n++) if (V(`adx${n}.used`)) out.push([`Admix ${n}`, "L", V(`adx${n}.required`), V(`adx${n}.level`), V(`adx${n}.accuracy`), V(`adx${n}.filled`), V(`adx${n}.over_tol`) || V(`adx${n}.under_tol`), 2]);
  return out.filter(m => (m[2] ?? 0) > 0).map(([label, unit, required, batched, accuracy, complete, oot, d]) => ({ label, unit, required, batched, accuracy, complete, oot, d }));
}

function materialTable(mats) {
  if (!mats.length) return `<tr><td class="muted">No batch in progress.</td></tr>`;
  return `<tr><th>Material</th><th class="num">Required</th><th class="num">Batched</th><th class="num">Accuracy</th><th>State</th></tr>` +
    mats.map(m => `<tr><td>${esc(m.label)}</td><td class="num">${num(m.required, m.d)} ${m.unit}</td><td class="num">${num(m.batched, m.d)} ${m.unit}</td>
      <td class="num ${m.oot ? "oot" : ""}">${m.accuracy === null || m.accuracy === undefined ? "–" : (m.accuracy > 0 ? "+" : "") + num(m.accuracy, 2) + " %"}${m.oot ? " ⚠" : ""}</td>
      <td>${m.complete ? "Complete" : "In progress"}</td></tr>`).join("");
}

async function confirmAction(title, text) {
  $("#confirmTitle").textContent = title; $("#confirmText").textContent = text;
  const dlg = $("#confirmDlg");
  dlg.showModal();
  return new Promise(res => dlg.addEventListener("close", () => res(dlg.returnValue === "yes"), { once: true }));
}

async function control(action, body) {
  const labels = { start: "Start batch", pause: "Pause batch", resume: "Resume batch", abort: "Abort batch" };
  const text = action === "start" ? `Start a ${Number(body.quantity).toFixed(2)} m³ batch?` :
    action === "abort" ? "Abort the running batch? Material already weighed stays in the plant." : `${labels[action]}?`;
  if (!await confirmAction(labels[action], text)) return;
  try { await api(`/api/control/${action}`, { body: body || {} }); $("#ctlNotice").innerHTML = `<div class="notice ok">${labels[action]}: sent.</div>`; }
  catch (e) { $("#ctlNotice").innerHTML = `<div class="notice error">${esc(labels[action])} refused: ${esc(e.message)}</div>`; }
}

// ---------- alarms ----------
function renderActiveAlarms() {
  const list = S.snap?.alarms || [];
  const can = S.user && ["operator", "admin"].includes(S.user.role);
  $("#ackAll").disabled = !can || !list.some(a => !a.acked);
  $("#alarmActive").innerHTML = list.length ? `<tr><th>Raised</th><th>Alarm</th><th>State</th><th></th></tr>` + list.map(a =>
    `<tr><td>${time(a.raised)}</td><td><span class="dot critical" style="display:inline-block;margin-right:6px"></span>${esc(a.text)}</td>
     <td>${a.acked ? `Acknowledged by ${esc(a.acked_by)}` : "<b>Unacknowledged</b>"}</td>
     <td>${a.acked ? "" : `<button data-ack="${a.id}" ${can ? "" : "disabled"}>Acknowledge</button>`}</td></tr>`).join("")
    : `<tr><td class="muted">No active alarms.</td></tr>`;
}
async function loadAlarmHistory() {
  const rows = await api(`/api/alarms?hours=${$("#alarmHours").value}`);
  $("#alarmHistory").innerHTML = `<tr><th>Raised</th><th>Alarm</th><th>Cleared</th><th>Acknowledged</th></tr>` + rows.map(a =>
    `<tr><td>${time(a.raised)}</td><td>${esc(a.text)}</td><td>${a.cleared ? time(a.cleared) : "<b>Active</b>"}</td>
     <td>${a.acked ? `${time(a.acked)} · ${esc(a.acked_by)}` : ""}</td></tr>`).join("");
}
async function ack(id) {
  try { await api(`/api/alarms/${id}/ack`, { body: {} }); } catch (e) { if (!S.user) openLogin(); else alert(e.message); }
}

// ---------- trends ----------
async function buildTrendPicker() {
  const tags = await api("/api/trend-tags");
  if (!S.trendKeys.length) S.trendKeys = ["bin1.current", "bin2.current", "bin3.current"];
  let html = "", grp = "";
  for (const t of tags) {
    const g = S.tags[t.key].group;
    if (g !== grp) { html += `<div class="grp">${esc(g)}</div>`; grp = g; }
    html += `<label><input type="checkbox" value="${t.key}" ${S.trendKeys.includes(t.key) ? "checked" : ""}> ${esc(S.tags[t.key].label)} <span class="muted small">${esc(t.unit)}</span></label>`;
  }
  $("#trendPicker").innerHTML = `<h2>Tags (max 8)</h2>` + html;
}

async function loadTrends() {
  if (!$("#trendPicker").children.length) await buildTrendPicker();
  const box = $("#trendCharts");
  if (!S.trendKeys.length) { box.innerHTML = `<div class="card muted">Pick tags on the left.</div>`; return; }
  const t1 = Date.now() / 1000, t0 = t1 - S.trendRange;
  const data = await api(`/api/trends?keys=${S.trendKeys.join(",")}&t0=${t0}&t1=${t1}&points=500`);
  // One chart per unit, so every chart has a single y-axis.
  const byUnit = {};
  S.trendKeys.forEach((k, i) => (byUnit[S.tags[k].unit] ||= []).push({ key: k, color: SERIES[i % 8], pts: data.series[k] || [] }));
  box.innerHTML = Object.entries(byUnit).map(([u], i) => `<div class="card chart" id="chart${i}"></div>`).join("");
  Object.entries(byUnit).forEach(([u, series], i) =>
    S.trendTable ? trendTableView($("#chart" + i), u, series) : drawChart($("#chart" + i), u, series, data.t0, data.t1));
}

function seriesLabel(k) { const t = S.tags[k]; return `${t.group} ${t.label}`; }

function drawChart(el, u, series, t0, t1) {
  const W = el.clientWidth - 24 || 800, H = 260, m = { l: 56, r: 12, t: 10, b: 24 };
  let lo = Infinity, hi = -Infinity;
  for (const s of series) for (const p of s.pts) { lo = Math.min(lo, p.min); hi = Math.max(hi, p.max); }
  if (!isFinite(lo)) { el.innerHTML = `<h2>${esc(u || "value")}</h2><p class="muted">No data in this range yet.</p>`; return; }
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  if (lo > 0 && lo < (hi - lo) * 0.5) lo = 0;
  const x = t => m.l + (t - t0) / (t1 - t0) * (W - m.l - m.r), y = v => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const ticks = niceTicks(lo, hi, 5), tt = timeTicks(t0, t1, Math.max(3, Math.floor(W / 120)));
  // Values are stored on change, so draw steps: each value holds until the next sample.
  const path = pts => pts.map((p, i) => (i ? `H${x(p.ts).toFixed(1)}V${y(p.avg).toFixed(1)}` : `M${x(p.ts).toFixed(1)},${y(p.avg).toFixed(1)}`)).join("") +
    (pts.length ? `H${x(Math.min(t1, Date.now() / 1000)).toFixed(1)}` : "");
  el.innerHTML = `<h2>${esc(u || "value")}</h2>
    <div class="legend">${series.map(s => `<span style="--c:var(${s.color})">${esc(seriesLabel(s.key))}</span>`).join("")}</div>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Trend ${esc(u)}">
      <g class="grid">${ticks.map(v => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/>`).join("")}</g>
      <g class="axis">${ticks.map(v => `<text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${num(v, Math.abs(hi - lo) < 10 ? 1 : 0)}</text>`).join("")}
        ${tt.map(t => `<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${tLabel(t, t1 - t0)}</text>`).join("")}</g>
      <g class="series">${series.map(s => `<path d="${path(s.pts)}" style="stroke:var(${s.color})"/>`).join("")}</g>
      <line class="cross" y1="${m.t}" y2="${H - m.b}" visibility="hidden"/>
      <rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/>
    </svg><div class="tip"></div>`;
  const svg = el.querySelector("svg"), cross = el.querySelector(".cross"), tip = el.querySelector(".tip");
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) / r.width * W;
    if (px < m.l) return;
    const t = t0 + (px - m.l) / (W - m.l - m.r) * (t1 - t0);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
    const rows = series.map(s => { let v = null; for (const p of s.pts) { if (p.ts <= t) v = p.avg; else break; }
      return `<div><span style="color:var(${s.color})">■</span> ${esc(seriesLabel(s.key))}: <b>${v === null ? "–" : num(v, S.tags[s.key].decimals)}</b></div>`; });
    tip.innerHTML = `<div class="muted">${new Date(t * 1000).toLocaleString()}</div>` + rows.join("");
    tip.style.display = "block";
    const left = ev.clientX - el.getBoundingClientRect().left;
    tip.style.left = Math.min(left + 12, el.clientWidth - tip.offsetWidth - 4) + "px"; tip.style.top = "40px";
  });
  svg.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); tip.style.display = "none"; });
}

function trendTableView(el, u, series) {
  const ts = [...new Set(series.flatMap(s => s.pts.map(p => p.ts)))].sort((a, b) => b - a).slice(0, 300);
  const val = (s, t) => { let v = null; for (const p of s.pts) { if (p.ts <= t) v = p.avg; else break; } return v; };
  el.innerHTML = `<h2>${esc(u)}</h2><div class="scroll" style="max-height:400px"><table><tr><th>Time</th>${series.map(s => `<th class="num">${esc(seriesLabel(s.key))}</th>`).join("")}</tr>` +
    ts.map(t => `<tr><td>${time(t)}</td>${series.map(s => `<td class="num">${num(val(s, t), S.tags[s.key].decimals)}</td>`).join("")}</tr>`).join("") + `</table></div>`;
}

function niceTicks(lo, hi, n) {
  const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0)), f = step0 / mag;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag, out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(+v.toFixed(10));
  return out;
}
function timeTicks(t0, t1, n) {
  const steps = [60, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400];
  const step = steps.find(s => (t1 - t0) / s <= n) || 86400, out = [];
  const off = new Date().getTimezoneOffset() * 60;
  for (let t = Math.ceil((t0 - off) / step) * step + off; t <= t1; t += step) out.push(t);
  return out;
}
function tLabel(t, span) {
  const d = new Date(t * 1000);
  return span > 86400 ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString([], { hour: "2-digit" })
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ---------- batches ----------
async function loadBatches() {
  const days = $("#batchDays").value;
  $("#batchCsv").href = `/api/batches.csv?days=${days}`;
  const rows = await api(`/api/batches?days=${days}`);
  S.batches = rows;
  $("#batchTable").innerHTML = rows.length ? `<tr><th>#</th><th>Started</th><th class="num">Duration</th><th class="num">Quantity</th><th>Status</th><th>Tolerance</th></tr>` +
    rows.map(b => {
      const oot = Object.values(b.detail.materials || {}).filter(m => m.over_tol || m.under_tol).map(m => m.label);
      return `<tr class="clickable" data-batch="${b.id}"><td>${b.id}</td><td>${time(b.started)}</td>
        <td class="num">${b.ended ? hms(b.ended - b.started) : "running"}</td><td class="num">${num(b.quantity, 2)} m³</td>
        <td class="status-${b.status}">${esc(b.status)}</td><td class="${oot.length ? "oot" : "muted"}">${oot.length ? "⚠ " + esc(oot.join(", ")) : "OK"}</td></tr>`;
    }).join("") : `<tr><td class="muted">No batches in this period.</td></tr>`;
}
function showBatch(id) {
  const b = S.batches.find(x => x.id === id);
  if (!b) return;
  $("#batchDetailCard").hidden = false;
  $("#batchDetailTitle").textContent = `Batch #${b.id} · ${time(b.started)} · ${num(b.quantity, 2)} m³ · ${b.status}${b.detail.paused ? " · was paused" : ""}`;
  const mats = Object.values(b.detail.materials || {}).map(m => ({ ...m, oot: m.over_tol || m.under_tol, d: m.unit === "kg" ? 0 : 2 }));
  $("#batchDetail").innerHTML = mats.length ? materialTable(mats) : `<tr><td class="muted">${esc(b.detail.note || "No material data.")}</td></tr>`;
  $("#batchDetailCard").scrollIntoView({ behavior: "smooth" });
}

// ---------- events ----------
async function loadEvents() {
  const rows = await api("/api/events");
  $("#eventTable").innerHTML = `<tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th></tr>` + rows.map(e =>
    `<tr><td>${time(e.ts)}</td><td>${esc(e.user || "")}</td><td class="${e.ok ? "" : "oot"}">${esc(e.action)}</td><td>${esc(e.detail)}</td></tr>`).join("");
}

// ---------- tags ----------
function renderTags() {
  const f = $("#tagFilter").value.toLowerCase();
  $("#tagInfo").textContent = S.snap?.connected ? `Updated ${new Date(S.snap.ts * 1000).toLocaleTimeString()} · ${S.snap.poll_ms} ms read` : (S.snap?.error || "");
  const rows = S.meta.tags.filter(t => !f || `${t.key} ${t.label} ${t.group} ${t.address}`.toLowerCase().includes(f));
  $("#tagTable").innerHTML = `<tr><th>Group</th><th>Tag</th><th>Address</th><th>Type</th><th class="num">Value</th></tr>` +
    rows.map(t => `<tr><td>${esc(t.group)}</td><td>${esc(t.label)} <span class="muted small">${esc(t.key)}</span></td><td>${esc(t.address)}</td><td>${t.type}</td>
      <td class="num">${fmt(t.key)}${t.type === "bool" ? "" : esc(unit(t.key))}</td></tr>`).join("");
}

// ---------- login / theme ----------
// Built here, not in index.html: a downloaded HTML file with a password form looks like phishing
// to antivirus heuristics (Defender flagged it as Trojan:Script/Wacatac.H!ml).
function loginDialog() {
  let dlg = $("#loginDlg");
  if (dlg) return dlg;
  const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
  const field = (label, name, type, autocomplete) => el("label", {}, label, el("input", { name, type, autocomplete, required: true }));
  const err = el("div", { className: "notice error", id: "loginErr", hidden: true });
  const cancel = el("button", { type: "button", textContent: "Cancel" });
  const form = el("form", { method: "dialog" }, el("h3", { textContent: "Log in" }),
    field("Username", "username", "text", "username"), field("Password", "password", "password", "current-password"), err,
    el("div", { className: "row" }, el("button", { className: "primary", type: "submit", textContent: "Log in" }), cancel));
  dlg = el("dialog", { id: "loginDlg" }, form);
  cancel.onclick = () => dlg.close();
  form.onsubmit = async ev => {
    ev.preventDefault();
    const fd = new FormData(form);
    try { await api("/api/login", { body: { username: fd.get("username"), password: fd.get("password") } }); dlg.close(); refreshUser(); }
    catch (e) { err.textContent = e.message; err.hidden = false; }
  };
  document.body.append(dlg);
  return dlg;
}
function openLogin() { const dlg = loginDialog(); $("#loginErr").hidden = true; dlg.querySelector("form").reset(); dlg.showModal(); }
async function refreshUser() {
  const me = await api("/api/me");
  S.user = me.username ? me : null;
  $("#userBtn").textContent = S.user ? `${S.user.username} · Log out` : "Log in";
  render();
}

function setup() {
  window.addEventListener("hashchange", route);
  $("#userBtn").onclick = async () => { if (S.user) { await api("/api/logout", { body: {} }); refreshUser(); } else openLogin(); };
  $("#themeBtn").onclick = () => {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    const cur = document.documentElement.dataset.theme || (dark ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { }
    if (S.page === "trends") loadTrends();
  };
  $("#bannerAck").onclick = () => ack($("#bannerAck").dataset.id);
  $("#ackAll").onclick = async () => { try { await api("/api/alarms/ack-all", { body: {} }); } catch (e) { alert(e.message); } };
  document.body.addEventListener("click", ev => {
    const a = ev.target.closest("[data-ack]"); if (a) ack(a.dataset.ack);
    const b = ev.target.closest("[data-batch]"); if (b) showBatch(+b.dataset.batch);
  });
  $("#alarmHours").onchange = loadAlarmHistory;
  $("#batchDays").onchange = loadBatches;
  $("#tagFilter").oninput = renderTags;
  $("#btnStart").onclick = () => control("start", { quantity: parseFloat($("#ctlQty").value) });
  $("#btnPause").onclick = () => control("pause");
  $("#btnResume").onclick = () => control("resume");
  $("#btnAbort").onclick = () => control("abort");
  $("#trendPicker").addEventListener("change", ev => {
    const keys = [...document.querySelectorAll("#trendPicker input:checked")].map(i => i.value);
    if (keys.length > 8) { ev.target.checked = false; return; }
    S.trendKeys = keys; loadTrends();
  });
  $("#trendRange").onclick = ev => {
    const b = ev.target.closest("button"); if (!b) return;
    document.querySelectorAll("#trendRange button").forEach(x => x.classList.toggle("on", x === b));
    S.trendRange = +b.dataset.s; loadTrends();
  };
  $("#trendTable").onclick = () => { S.trendTable = !S.trendTable; $("#trendTable").textContent = S.trendTable ? "Chart view" : "Table view"; loadTrends(); };
  setInterval(() => {
    $("#clock").textContent = new Date().toLocaleTimeString();
    if (S.page === "overview") renderOverview();
  }, 1000);
  setInterval(() => { if (S.page === "trends" && $("#trendLive").checked && !document.hidden) loadTrends(); }, 10000);
  setInterval(() => { if (S.page === "alarms") loadAlarmHistory(); if (S.page === "batches") loadBatches(); if (S.page === "events") loadEvents(); }, 15000);
}

(async function init() {
  try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { }
  setup();
  S.meta = await api("/api/meta");
  for (const t of S.meta.tags) S.tags[t.key] = t;
  S.snap = await api("/api/snapshot");
  await refreshUser();
  route();
  connect();
})();
