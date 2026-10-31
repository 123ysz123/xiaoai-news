/* 小爱新闻播报控制台 */
const API = "./api";
let cfg = null;      // 本地配置副本，编辑后点保存才落盘
let dirty = false;

/* ---------------- 基础 ---------------- */
function toast(msg, type) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast show " + (type || "");
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = "toast"), 2600);
}

async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (opts.body) headers["Content-Type"] = "application/json";

  const resp = await fetch(API + path, { ...opts, headers });
  const text = await resp.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { error: text }; }
  if (!resp.ok) throw new Error(data.error || data.detail || `HTTP ${resp.status}`);
  return data;
}

/* ---------------- 初始化 ---------------- */
async function init() {
  try {
    cfg = await api("/config");
    buildStaticSelects();
    renderAll();
    loadStatus();
    loadLogs();
    loadHistory();
    initKnob();
    loadVolume();
  } catch (e) {
    toast("加载配置失败：" + e.message, "err");
  }
}

function buildStaticSelects() {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  ["quiet-start", "quiet-end"].forEach((id) => {
    const el = document.getElementById(id);
    el.innerHTML = hours.map((h) => `<option value="${h}">${String(h).padStart(2, "0")}:00</option>`).join("");
  });
  document.getElementById("ns-cat").innerHTML = ["国内", "国际", "财经", "科技", "社会", "体育"]
    .map((c) => `<option value="${c}">${c}</option>`).join("");
}

/* ---------------- 渲染 ---------------- */
function renderAll() {
  renderHours();
  renderSources();
  renderCats();
  fillForm();
}

function renderHours() {
  const on = new Set(cfg.schedule.hours);
  const qs = +cfg.schedule.quiet_start, qe = +cfg.schedule.quiet_end;
  const inQuiet = (h) => {
    if (qs === qe) return false;
    return qs < qe ? h >= qs && h < qe : h >= qs || h < qe;
  };
  document.getElementById("hours").innerHTML = Array.from({ length: 24 }, (_, h) => {
    const cls = ["hour", on.has(h) ? "on" : "", inQuiet(h) ? "quiet" : ""].join(" ");
    return `<div class="${cls}" data-h="${h}" onclick="toggleHour(${h})">${String(h).padStart(2, "0")}</div>`;
  }).join("");
  document.getElementById("quiet-start").value = qs;
  document.getElementById("quiet-end").value = qe;
}

function toggleHour(h) {
  const set = new Set(cfg.schedule.hours);
  set.has(h) ? set.delete(h) : set.add(h);
  cfg.schedule.hours = [...set].sort((a, b) => a - b);
  dirty = true;
  renderHours();
}

function preset(kind) {
  const map = { morning: [7, 8], noon: [12], evening: [18, 21], all: Array.from({ length: 24 }, (_, i) => i), clear: [] };
  cfg.schedule.hours = map[kind];
  dirty = true;
  renderHours();
}

function renderSources() {
  const box = document.getElementById("sources");
  if (!cfg.sources.length) {
    box.innerHTML = '<div class="empty">暂无新闻源</div>';
    return;
  }
  box.innerHTML = cfg.sources.map((s, i) => `
    <div class="src ${s.enabled ? "" : "off"}">
      <div class="idx">${i + 1}</div>
      <div>
        <div class="nm">${esc(s.name)}</div>
        <div class="meta">${esc(s.url)}</div>
      </div>
      <div><span class="tag cat">${esc(s.category)}</span></div>
      <div class="row" style="gap:4px;flex-wrap:nowrap">
        <label class="switch"><input type="checkbox" ${s.enabled ? "checked" : ""} onchange="toggleSource(${i})"><span class="slider"></span></label>
        <button class="sm" onclick="moveSource(${i},-1)" ${i === 0 ? "disabled" : ""}>↑</button>
        <button class="sm" onclick="moveSource(${i},1)" ${i === cfg.sources.length - 1 ? "disabled" : ""}>↓</button>
        <button class="sm danger" onclick="delSource(${i})">删</button>
      </div>
    </div>`).join("");
}

function renderCats() {
  const on = new Set(cfg.rules.categories);
  document.getElementById("cats").innerHTML = ["国内", "国际", "财经", "科技", "社会", "体育"]
    .map((c) => `<div class="chip ${on.has(c) ? "on" : ""}" onclick="toggleCat('${c}')">${c}</div>`).join("");
}

function toggleCat(c) {
  const set = new Set(cfg.rules.categories);
  if (set.has(c)) set.delete(c); else set.add(c);
  if (!set.size) { toast("至少保留一个类型", "err"); return; }
  cfg.rules.categories = [...set];
  dirty = true;
  renderCats();
}

function fillForm() {
  const r = cfg.rules, t = cfg.tts;
  document.getElementById("r-chars").value = r.max_chars_per_item;
  document.getElementById("r-items").value = r.max_items;
  document.getElementById("r-dur").value = r.max_duration_sec;
  document.getElementById("r-cps").value = r.chars_per_sec;
  document.getElementById("r-dedup-h").value = r.dedup_hours;
  document.getElementById("r-dedup").checked = !!r.dedup;
  document.getElementById("a-did").value = t.did || "";
  document.getElementById("a-url").value = t.url || "";
  document.getElementById("a-retry").value = t.retry;
  document.getElementById("a-timeout").value = t.timeout;
  document.getElementById("a-keep").value = cfg.history.keep_days;
  document.getElementById("a-intro").value = t.intro || "";
  document.getElementById("a-outro").value = t.outro || "";
  document.getElementById("a-pause").checked = !!t.pause_music;
}

function collectForm() {
  const r = cfg.rules, t = cfg.tts;
  r.max_chars_per_item = +document.getElementById("r-chars").value;
  r.max_items = +document.getElementById("r-items").value;
  r.max_duration_sec = +document.getElementById("r-dur").value;
  r.chars_per_sec = +document.getElementById("r-cps").value;
  r.dedup_hours = +document.getElementById("r-dedup-h").value;
  r.dedup = document.getElementById("r-dedup").checked;
  t.did = document.getElementById("a-did").value.trim();
  t.url = document.getElementById("a-url").value.trim();
  t.retry = +document.getElementById("a-retry").value;
  t.timeout = +document.getElementById("a-timeout").value;
  t.intro = document.getElementById("a-intro").value;
  t.outro = document.getElementById("a-outro").value;
  t.pause_music = document.getElementById("a-pause").checked;
  cfg.history.keep_days = +document.getElementById("a-keep").value;
  cfg.schedule.quiet_start = +document.getElementById("quiet-start").value;
  cfg.schedule.quiet_end = +document.getElementById("quiet-end").value;
  return cfg;
}

/* ---------------- 源操作 ---------------- */
function toggleSource(i) { cfg.sources[i].enabled = !cfg.sources[i].enabled; dirty = true; renderSources(); }
function moveSource(i, d) {
  const j = i + d;
  if (j < 0 || j >= cfg.sources.length) return;
  [cfg.sources[i], cfg.sources[j]] = [cfg.sources[j], cfg.sources[i]];
  dirty = true; renderSources();
}
function delSource(i) {
  if (!confirm(`删除新闻源「${cfg.sources[i].name}」？`)) return;
  cfg.sources.splice(i, 1); dirty = true; renderSources();
}
function addSource() {
  const name = document.getElementById("ns-name").value.trim();
  const url = document.getElementById("ns-url").value.trim();
  const cat = document.getElementById("ns-cat").value;
  if (!name || !url) { toast("请填写名称和 RSS 地址", "err"); return; }
  if (!/^https?:\/\//.test(url)) { toast("RSS 地址需以 http:// 或 https:// 开头", "err"); return; }
  cfg.sources.push({ id: "custom-" + Date.now(), name, url, category: cat, enabled: true });
  document.getElementById("ns-name").value = "";
  document.getElementById("ns-url").value = "";
  dirty = true; renderSources();
  toast("已添加，记得点保存配置", "ok");
}

/* ---------------- 保存 ---------------- */
async function saveConfig() {
  const btn = document.getElementById("btn-save");
  btn.disabled = true; btn.textContent = "保存中…";
  try {
    const data = collectForm();
    const res = await api("/config", { method: "POST", body: JSON.stringify(data) });
    cfg = res.config;
    dirty = false;
    renderAll();
    loadStatus();
    toast("配置已保存，定时任务已热更新", "ok");
  } catch (e) {
    toast("保存失败：" + e.message, "err");
  } finally {
    btn.disabled = false; btn.textContent = "保存配置";
  }
}

async function resetConfig() {
  if (!confirm("恢复默认配置？当前所有自定义设置（含自定义新闻源）将丢失。")) return;
  try {
    const res = await api("/config/reset", { method: "POST" });
    cfg = res.config; dirty = false;
    renderAll(); loadStatus();
    toast("已恢复默认配置", "ok");
  } catch (e) { toast("操作失败：" + e.message, "err"); }
}

/* ---------------- 执行 ---------------- */
async function doPreview() {
  const btn = document.getElementById("btn-preview");
  btn.disabled = true; btn.textContent = "拉取中…";
  document.getElementById("preview").innerHTML = '<div class="empty">正在拉取各新闻源…</div>';
  try {
    const res = await api("/preview", { method: "POST", body: JSON.stringify({}) });
    renderPreview(res);
    toast(`拉取完成，共 ${res.total} 条`, "ok");
    loadLogs();
  } catch (e) {
    document.getElementById("preview").innerHTML = `<div class="empty">拉取失败：${esc(e.message)}</div>`;
    toast("拉取失败：" + e.message, "err");
  } finally {
    btn.disabled = false; btn.textContent = "立即拉取测试";
  }
}

function renderPreview(res) {
  const s = res.stats || {};
  document.getElementById("preview-meta").textContent =
    `源 ${s.sources || 0} · 抓取 ${s.fetched || 0} · 过滤后 ${s.after_filter || 0} · 选中 ${s.selected || 0} · 预计 ${s.est_seconds || 0}s`;
  const box = document.getElementById("preview");
  if (!res.items || !res.items.length) {
    box.innerHTML = '<div class="empty">没有符合条件的新闻（检查分类筛选或去重设置）</div>';
    return;
  }
  box.innerHTML = res.items.map((it, i) => `
    <div class="news-item">
      <div class="t">${i + 1}. ${esc(it.title)}</div>
      <div class="m">${esc(it.source)} · ${esc(it.category)}${it.summary ? " · " + esc(it.summary) : ""}</div>
    </div>`).join("");
  if (s.failed && s.failed.length) {
    box.innerHTML += `<div class="hint">拉取失败的源：${s.failed.map(esc).join("；")}</div>`;
  }
}

async function doBroadcast() {
  if (!confirm("立即让小爱音箱播报一次新闻？")) return;
  const btn = document.getElementById("btn-broadcast");
  btn.disabled = true; btn.textContent = "播报中…";
  try {
    const res = await api("/broadcast", { method: "POST", body: JSON.stringify({}) });
    renderPreview({ items: res.items || [], stats: res.stats || {} });
    toast(res.ok ? `播报已提交（${res.record.count} 条，${res.record.chars} 字）` : "播报失败，详见日志", res.ok ? "ok" : "err");
    loadLogs(); loadHistory(); loadStatus();
  } catch (e) {
    toast("播报失败：" + e.message, "err");
    loadLogs();
  } finally {
    btn.disabled = false; btn.textContent = "立即播报测试";
  }
}

/* ---------------- 状态 / 日志 / 历史 ---------------- */
async function loadStatus() {
  try {
    const s = await api("/status");
    const sch = document.getElementById("st-sched");
    sch.textContent = s.scheduler_running ? "运行中" : "已停止";
    sch.className = "v " + (s.scheduler_running ? "ok" : "err");

    document.getElementById("st-next").textContent = s.next_run || "无可用时段";

    // 下一个定时点落在静音时段时，明确标出「会被跳过」
    const note = document.getElementById("st-next-note");
    if (s.next_scheduled && s.next_run && s.next_scheduled !== s.next_run) {
      note.textContent = `${s.next_scheduled.slice(11, 16)} 静音跳过`;
    } else if (s.next_scheduled && !s.next_run) {
      note.textContent = "所有时段均在静音内";
    } else {
      note.textContent = "";
    }

    document.getElementById("st-src").textContent = `${s.enabled_source_count} / ${s.source_count}`;

    const q = document.getElementById("st-quiet");
    q.textContent = s.quiet ? "静音时段" : "正常播报";
    q.className = "v " + (s.quiet ? "warn" : "ok");
    document.getElementById("st-quiet-note").textContent = s.quiet_window || "";
  } catch (e) { /* 忽略 */ }
}

async function loadLogs() {
  try {
    const res = await api("/logs?limit=100");
    const box = document.getElementById("logs");
    box.textContent = (res.logs || []).join("\n") || "暂无日志";
    box.scrollTop = box.scrollHeight;
  } catch (e) { /* 忽略 */ }
}

async function loadHistory() {
  try {
    const res = await api("/history?limit=5");
    if (!res.records || !res.records.length) return;
    console.log("最近播报", res.records);
  } catch (e) { /* 忽略 */ }
}

/* ---------------- 音量旋钮 ---------------- */
const VOL_ARC = 245.04;   // 270° 弧长（r=52）
const VOL_CIRC = 326.73;  // 整圆周长
let vol = 50, muted = false, volTimer = null, dragging = false;

function renderVolume(v, m) {
  vol = Math.max(0, Math.min(100, Math.round(v)));
  muted = !!m;
  const knob = document.getElementById("knob");
  if (!knob) return;

  document.getElementById("knob-prog")
    .setAttribute("stroke-dasharray", `${(VOL_ARC * vol / 100).toFixed(2)} ${VOL_CIRC}`);
  document.getElementById("knob-needle")
    .setAttribute("transform", `rotate(${(-135 + 2.7 * vol).toFixed(1)} 70 70)`);
  document.getElementById("vol-num").textContent = muted ? 0 : vol;
  document.getElementById("vol-label").textContent = muted ? "已静音" : "音量";
  knob.classList.toggle("muted", muted);
  knob.setAttribute("aria-valuenow", vol);

  const btn = document.getElementById("btn-mute");
  btn.classList.toggle("on", muted);
  document.getElementById("mute-icon").textContent = muted ? "🔇" : "🔊";
  document.getElementById("mute-text").textContent = muted ? "取消静音" : "立即静音";
  document.getElementById("vol-state").textContent = muted ? "当前静音中" : `当前音量 ${vol}`;
}

/* 把鼠标位置换算成 0-100 的音量值（旋钮从 -135° 到 +135°） */
function angleToVolume(clientX, clientY) {
  const r = document.getElementById("knob").getBoundingClientRect();
  const dx = clientX - (r.left + r.width / 2);
  const dy = clientY - (r.top + r.height / 2);
  const a = Math.atan2(dy, dx) * 180 / Math.PI;      // -180..180，0 为正右方
  const n = ((a - 135) % 360 + 360) % 360;           // 0 对应左下角起点
  let ratio;
  if (n <= 270) ratio = n / 270;
  else ratio = n < 315 ? 1 : 0;                      // 底部死区吸附到两端
  return Math.round(Math.max(0, Math.min(1, ratio)) * 100);
}

async function sendVolume(v, delay = 0) {
  clearTimeout(volTimer);
  const run = async () => {
    try {
      const res = await api("/volume", { method: "POST", body: JSON.stringify({ volume: v }) });
      renderVolume(res.volume, res.muted);
    } catch (e) {
      toast("音量设置失败：" + e.message, "err");
    }
  };
  if (delay) volTimer = setTimeout(run, delay);
  else run();
}

function quickVolume(v) {
  renderVolume(v, false);
  sendVolume(v);
}

async function toggleMute() {
  const btn = document.getElementById("btn-mute");
  btn.disabled = true;
  try {
    const res = await api("/mute", { method: "POST", body: JSON.stringify({ mute: !muted }) });
    renderVolume(res.volume, res.muted);
    toast(res.muted ? "已静音" : `已恢复音量 ${res.volume}`, "ok");
  } catch (e) {
    toast("操作失败：" + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

async function loadVolume() {
  try {
    const r = await api("/volume");
    renderVolume(r.volume, r.muted);
  } catch (e) {
    document.getElementById("vol-num").textContent = "--";
    document.getElementById("vol-state").textContent = "音量不可用";
  }
}

function initKnob() {
  const knob = document.getElementById("knob");
  if (!knob) return;

  knob.addEventListener("pointerdown", (e) => {
    dragging = true;
    knob.setPointerCapture(e.pointerId);
    renderVolume(angleToVolume(e.clientX, e.clientY), false);
    e.preventDefault();
  });
  knob.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    renderVolume(angleToVolume(e.clientX, e.clientY), false);
  });
  knob.addEventListener("pointerup", (e) => {
    if (!dragging) return;
    dragging = false;
    try { knob.releasePointerCapture(e.pointerId); } catch (_) {}
    sendVolume(vol);
  });
  knob.addEventListener("pointercancel", () => { dragging = false; });

  knob.addEventListener("wheel", (e) => {
    e.preventDefault();
    const next = Math.max(0, Math.min(100, vol + (e.deltaY < 0 ? 5 : -5)));
    renderVolume(next, false);
    sendVolume(next, 350);
  }, { passive: false });

  knob.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 10 : 5;
    let next = null;
    if (e.key === "ArrowUp" || e.key === "ArrowRight") next = Math.min(100, vol + step);
    else if (e.key === "ArrowDown" || e.key === "ArrowLeft") next = Math.max(0, vol - step);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = 100;
    if (next !== null) {
      e.preventDefault();
      renderVolume(next, false);
      sendVolume(next, 350);
    }
  });
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

window.addEventListener("beforeunload", (e) => {
  if (dirty) { e.preventDefault(); e.returnValue = ""; }
});

init();
