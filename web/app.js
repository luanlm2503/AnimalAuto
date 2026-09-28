"use strict";
// Animal TV Generator — plain JS front end (no build step).

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ANIMS = ["idle", "walk", "run"];

let P = null;               // current project
let saveTimer = null;
let bgImg = null;

// ------------------------------------------------------------------ helpers -------------
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (err ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), err ? 6000 : 2500);
}

async function api(method, url, body, raw = false) {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) {
    opt.body = JSON.stringify(body);
    opt.headers["Content-Type"] = "application/json";
  }
  const r = await fetch(url, opt);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
    throw new Error(msg);
  }
  return raw ? r : r.json();
}

function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}
function setPath(obj, path, val) {
  const ks = path.split(".");
  let o = obj;
  for (const k of ks.slice(0, -1)) o = o[k];
  o[ks.at(-1)] = val;
}
function readInput(el) {
  if (el.type === "checkbox") return el.checked;
  const t = el.dataset.type;
  if (t === "int") return parseInt(el.value, 10) || 0;
  if (t === "intnull") return el.value.trim() === "" ? null : parseInt(el.value, 10);
  if (el.type === "range" || el.type === "number") return parseFloat(el.value) || 0;
  return el.value;
}
function writeInput(el, v) {
  if (el.type === "checkbox") el.checked = !!v;
  else el.value = v ?? "";
  const out = el.nextElementSibling;
  if (out && out.tagName === "OUTPUT") out.textContent = el.value;
}
function fmtTime(s) {
  if (s == null || !isFinite(s)) return "–";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}h${String(m).padStart(2, "0")}m` : m ? `${m}m${String(x).padStart(2, "0")}s` : `${x}s`;
}

// ------------------------------------------------------------------ project ------------
async function loadProjects(selectId) {
  const list = await api("GET", "/api/projects");
  const sel = $("#projSel");
  sel.innerHTML = "";
  for (const p of list) sel.add(new Option(p.name, p.id));
  if (!list.length) {
    const p = await api("POST", "/api/projects", { name: "Mouse TV" });
    return loadProjects(p.id);
  }
  const want = selectId || localStorageGet("project") || list[0].id;
  sel.value = list.some(p => p.id === want) ? want : list[0].id;
  await openProject(sel.value);
}

function localStorageGet(k) { try { return localStorage.getItem("atv:" + k); } catch (_) { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem("atv:" + k, v); } catch (_) {} }

async function openProject(id) {
  P = await api("GET", `/api/projects/${id}`);
  localStorageSet("project", id);
  renderAll();
}

function setProject(p) {
  // keep UI-only state but take everything the server returned
  P = p;
  renderAll();
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 500);
}
async function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  try {
    // keep P as is: the cards hold references into it, and the server only merges UI fields
    await api("PUT", `/api/projects/${P.id}`, P);
    refreshLive();
  } catch (e) { toast("Lỗi lưu: " + e.message, true); }
}

// ------------------------------------------------------------------ render UI ----------
function renderAll() {
  // global bindings
  for (const el of $$("[data-bind]")) writeInput(el, getPath(P, el.dataset.bind));
  $("#durPreset").value = [...$("#durPreset").options].some(o => o.value === P.render.duration) ? P.render.duration : "";
  $("#resSel").value = `${P.render.width}x${P.render.height}`;
  $("#ambName").textContent = P.ambience ? "Âm nền: " + P.ambience.split("/").pop() + " (kéo file khác để thay)" : "Kéo thả âm nền (MP3/WAV), lặp suốt video";
  $("#stage").style.aspectRatio = `${P.render.width} / ${P.render.height}`;
  renderAnimals();
  loadBackground();
  refreshLive();
}

// ------------------------------------------------------------------ animals -------------
const PRESETS = {
  mouse:   { icon: "🐭", label: "Chuột",     name: "chuột",     size_pct: 7,   walk_speed: [60, 120], run_speed: [300, 500], pause: [0.3, 2.5], behaviors: { walk: 30, run: 35, idle: 20, turn: 8, hide: 7 } },
  hamster: { icon: "🐹", label: "Hamster",   name: "hamster",   size_pct: 6.5, walk_speed: [40, 90],  run_speed: [180, 300], pause: [0.5, 3.0], behaviors: { walk: 35, run: 20, idle: 35, turn: 8, hide: 2 } },
  cat:     { icon: "🐱", label: "Mèo",       name: "mèo",       size_pct: 18,  walk_speed: [70, 130], run_speed: [350, 600], pause: [1.0, 5.0], behaviors: { walk: 30, run: 15, idle: 45, turn: 8, hide: 2 } },
  dog:     { icon: "🐶", label: "Chó",       name: "chó",       size_pct: 20,  walk_speed: [90, 160], run_speed: [400, 700], pause: [0.5, 3.0], behaviors: { walk: 35, run: 30, idle: 25, turn: 8, hide: 2 } },
  bird:    { icon: "🐦", label: "Chim",      name: "chim",      size_pct: 6,   walk_speed: [40, 80],  run_speed: [150, 260], pause: [0.3, 2.0], behaviors: { walk: 30, run: 25, idle: 30, turn: 10, hide: 5 } },
  bug:     { icon: "🐞", label: "Côn trùng", name: "côn trùng", size_pct: 3.5, walk_speed: [25, 55],  run_speed: [80, 140],  pause: [0.5, 3.0], behaviors: { walk: 50, run: 10, idle: 30, turn: 10, hide: 0 } },
  fish:    { icon: "🐟", label: "Cá",        name: "cá",        size_pct: 10,  walk_speed: [50, 100], run_speed: [200, 350], pause: [0.2, 1.5], behaviors: { walk: 45, run: 15, idle: 25, turn: 10, hide: 5 } },
  other:   { icon: "✏️", label: "Khác…",     name: "",          size_pct: 7,   walk_speed: [60, 120], run_speed: [250, 450], pause: [0.4, 3.0], behaviors: { walk: 30, run: 30, idle: 25, turn: 8, hide: 7 } },
};
const SLOT = { idle: "Đứng yên", walk: "Đi", run: "Chạy" };
const KEY_DEFAULT = { enabled: true, tolerance: 22, softness: 14, shadow: 0, despill: 0.8, keep_largest: true };
const ui = {};                 // animalId -> { tab, slot, closed }; survives re-renders
const uiOf = id => (ui[id] ??= { tab: "clips", slot: null, closed: false });
let selectedAnimal = null;
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const hasClip = (a, n) => a.anims[n]?.frames > 0;

function hash(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = (h * 33 + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}
// changes whenever the stored frames change, so cached sheets/thumbs are refetched
const animVer = an => hash([an.src, an.frames, an.width, an.height, an.trim_start, an.trim_end, an.auto_loop, JSON.stringify(an.key_used)].join("|"));

function applyPreset(a, key) {
  const p = PRESETS[key];
  a.size_pct = p.size_pct;
  a.walk_speed = [...p.walk_speed];
  a.run_speed = [...p.run_speed];
  a.pause = [...p.pause];
  a.behaviors = { ...p.behaviors };
}

// simple 0..10 sliders <-> exact numbers
const mean = r => (r[0] + r[1]) / 2;
function normWeights(b) {
  const m = Math.max(...Object.values(b).map(Number));
  if (m > 100) for (const k in b) b[k] = Math.round(b[k] * 100 / m);
}
function speedLevel(a) { return clamp(Math.log(mean(a.walk_speed) / 25) / Math.log(1.35), 0, 10); }
function setSpeed(a, s) {
  const ratio = clamp(mean(a.run_speed) / Math.max(1, mean(a.walk_speed)) || 3.5, 1.5, 8);
  const base = 25 * 1.35 ** s;
  a.walk_speed = [Math.round(base * 0.67), Math.round(base * 1.33)];
  a.run_speed = [Math.round(base * ratio * 0.8), Math.round(base * ratio * 1.2)];
}
function activityLevel(a) {
  const b = a.behaviors, mv = (+b.walk || 0) + (+b.run || 0);
  return clamp((mv / Math.max(1e-6, mv + (+b.idle || 0)) - 0.2) / 0.075, 0, 10);
}
function setActivity(a, v) {
  const b = a.behaviors;
  let mv = (+b.walk || 0) + (+b.run || 0);
  if (mv <= 0) { b.walk = 30; b.run = 20; mv = 50; }
  const f = 0.2 + 0.075 * v;                       // share of time spent moving
  b.idle = Math.round(mv * (1 - f) / f);
  a.pause = [+lerp(1.5, 0.2, v / 10).toFixed(1), +lerp(7, 1.2, v / 10).toFixed(1)];
  normWeights(b);
}
function shyLevel(a) {
  const b = a.behaviors, t = Object.values(b).reduce((x, y) => x + (+y || 0), 0);
  return clamp((+b.hide || 0) / Math.max(1e-6, t) / 0.03, 0, 10);
}
function setShy(a, v) {
  const b = a.behaviors, h = 0.03 * v;
  const rest = (+b.walk || 0) + (+b.run || 0) + (+b.idle || 0) + (+b.turn || 0);
  b.hide = Math.round(rest * h / (1 - h));
  normWeights(b);
}

function renderAnimals() {
  const box = $("#animals");
  box.innerHTML = "";
  for (const a of P.animals) box.appendChild(animalCard(a));
  if (!P.animals.length) {
    box.innerHTML = `<p class="hint">Chưa có con vật. Chọn loài ở trên để thêm.</p>`;
    $("#presetPicker").hidden = false;
  }
}

function refreshCard(a) {
  const old = $(`.animal[data-id="${a.id}"]`);
  if (old) old.replaceWith(animalCard(a));
}

function selectAnimal(id, fromStage = false) {
  selectedAnimal = id;
  for (const c of $$(".animal")) c.classList.toggle("selected", c.dataset.id === id);
  if (!fromStage) return;
  const card = $(`.animal[data-id="${id}"]`);
  if (!card) return;
  uiOf(id).closed = false;
  card.classList.remove("closed");
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 600);
}

function animalCard(a) {
  const el = $("#animalTpl").content.firstElementChild.cloneNode(true);
  const st = uiOf(a.id);
  el.dataset.id = a.id;
  el.classList.toggle("closed", st.closed);
  el.classList.toggle("off", !a.enabled);
  el.classList.toggle("selected", selectedAnimal === a.id);
  const first = ANIMS.find(n => hasClip(a, n));
  if (first) $(".athumb img", el).src = `/api/projects/${P.id}/animals/${a.id}/anims/${first}/thumb?v=${animVer(a.anims[first])}`;

  for (const inp of $$("[data-a]", el)) {
    writeInput(inp, getPath(a, inp.dataset.a));
    inp.addEventListener(inp.type === "range" ? "input" : "change", () => {
      const k = inp.dataset.a;
      setPath(a, k, readInput(inp));
      writeInput(inp, getPath(a, k));
      if (k.startsWith("key.")) { keyPreview(el, a); updateKeyState(el, a); }
      if (k === "enabled") el.classList.toggle("off", !a.enabled);
      if (/^(behaviors|walk_speed|run_speed|pause)/.test(k)) syncSimple(el, a);
      scheduleSave();
    });
  }

  // header
  $(".ahead", el).addEventListener("click", e => {
    if (e.target.closest("input, button, label")) return;
    selectAnimal(a.id);
  });
  $(".fold", el).onclick = () => { st.closed = !st.closed; el.classList.toggle("closed", st.closed); };
  const cnt = $(".cnt", el);
  cnt.textContent = a.count;
  const setCount = d => { a.count = clamp(a.count + d, 1, 20); cnt.textContent = a.count; scheduleSave(); };
  $(".minus", el).onclick = () => setCount(-1);
  $(".plus", el).onclick = () => setCount(1);
  $(".del", el).onclick = async () => {
    if (!confirm(`Xóa con vật "${a.name}" và các clip của nó?`)) return;
    setProject(await api("DELETE", `/api/projects/${P.id}/animals/${a.id}`));
  };

  // tabs
  const showTab = name => {
    st.tab = name;
    for (const b of $$(".tabs button", el)) b.classList.toggle("on", b.dataset.tab === name);
    for (const t of $$(".tab", el)) t.classList.toggle("on", t.dataset.tab === name);
    if (name === "key") keyPreview(el, a);
  };
  for (const b of $$(".tabs button", el)) b.onclick = () => { showTab(b.dataset.tab); selectAnimal(a.id); };
  if (!first) st.tab = "clips";
  buildSlots(el, a);
  buildMotion(el, a);
  buildKey(el, a);
  buildSounds(el, a);
  showTab(st.tab);
  return el;
}

// ---- clips tab
function guessAnim(fname) {
  const n = fname.toLowerCase().replace(/đ/g, "d").normalize("NFD").replace(/[̀-ͯ]/g, "");
  if (/run|chay|sprint|dash|scurry/.test(n)) return "run";
  if (/walk|(^|[^a-z])di([^a-z]|$)|buoc/.test(n)) return "walk";
  if (/idle|stand|dung|ngoi|groom|sit|nghi|sniff/.test(n)) return "idle";
  return null;
}

// which slot each dropped file goes to: by file name first, then the target / empty slots
function planClips(a, files, target) {
  if (files.length === 1 && target) return [[target, files[0]]];
  const plan = [], used = new Set(), rest = [];
  for (const f of files) {
    const g = guessAnim(f.name);
    if (g && !used.has(g)) { plan.push([g, f]); used.add(g); } else rest.push(f);
  }
  const order = [target, ...ANIMS.filter(n => !hasClip(a, n)), ...ANIMS].filter(Boolean);
  for (const f of rest) {
    const n = order.find(n => !used.has(n));
    if (!n) break;
    plan.push([n, f]);
    used.add(n);
  }
  if (plan.length < files.length) toast(`Chỉ có 3 ô clip, bỏ qua ${files.length - plan.length} file`, true);
  return plan;
}

async function importClips(card, a, jobs) {
  if (!jobs.length) return;
  for (const [name] of jobs) $(`.slot[data-anim=${name}]`, card)?.classList.add("busy");
  await saveNow();   // key settings must be on the server before it keys the clip
  let last = null;
  for (const [name, fd] of jobs) {
    try {
      last = await api("POST", `/api/projects/${P.id}/animals/${a.id}/anims/${name}`, fd);
      toast(`Đã nhập clip “${SLOT[name]}”`);
    } catch (e) { toast(`Lỗi nhập clip “${SLOT[name]}”: ${e.message}`, true); }
    $(`.slot[data-anim=${name}]`, card)?.classList.remove("busy");
  }
  if (last) {
    uiOf(a.id).slot = jobs.at(-1)[0];
    setProject(last);
  }
}

function clipForm(an, file, over = {}) {
  const fd = new FormData();
  if (file) fd.append("file", file);
  fd.append("trim_start", over.trim_start ?? (file ? 0 : an?.trim_start ?? 0));
  fd.append("trim_end", over.trim_end ?? (file ? 0 : an?.trim_end ?? 0));
  fd.append("auto_loop", over.auto_loop ?? an?.auto_loop ?? false);
  return fd;
}

function dropFiles(target, onFiles) {
  target.addEventListener("dragover", e => { e.preventDefault(); e.stopPropagation(); target.classList.add("over"); });
  target.addEventListener("dragleave", () => target.classList.remove("over"));
  target.addEventListener("drop", e => {
    e.preventDefault();
    e.stopPropagation();
    target.classList.remove("over");
    const files = [...e.dataTransfer.files];
    if (files.length) onFiles(files);
  });
}

function buildSlots(card, a) {
  const st = uiOf(a.id);
  const box = $(".slots", card);
  const load = (files, target) => importClips(card, a, planClips(a, files, target).map(([n, f]) => [n, clipForm(a.anims[n], f)]));
  if (st.slot && !hasClip(a, st.slot)) st.slot = null;
  for (const name of ANIMS) {
    const an = a.anims[name];
    const has = hasClip(a, name);
    const s = document.createElement("div");
    s.className = "slot";
    s.dataset.anim = name;
    s.title = has ? "Bấm để chỉnh clip này" : "Bấm để chọn file, hoặc kéo thả clip vào";
    s.innerHTML = `<input type="file" accept="video/*,image/*,.zip" multiple>` +
      (has ? `<canvas class="checker" width="160" height="120"></canvas>` : `<div class="empty"><b>+</b>kéo clip<br>vào đây</div>`) +
      `<div class="lbl"></div>`;
    $(".lbl", s).innerHTML = `${SLOT[name]}<small>${name}${has ? " · " + an.frames + " frame" : ""}</small>`;
    const input = $("input", s);
    input.onclick = e => e.stopPropagation();
    input.onchange = () => { const f = [...input.files]; input.value = ""; if (f.length) load(f, name); };
    s.onclick = () => (has ? selectSlot(card, a, name) : input.click());
    dropFiles(s, files => load(files, name));
    if (has) Object.assign($("canvas", s).dataset, { aid: a.id, anim: name });
    box.appendChild(s);
  }
  dropFiles($(".tab[data-tab=clips]", card), files => load(files, null));
  if (st.slot) selectSlot(card, a, st.slot);
}

function selectSlot(card, a, name) {
  const st = uiOf(a.id);
  st.slot = name;
  for (const s of $$(".slot", card)) s.classList.toggle("sel", s.dataset.anim === name);
  const an = a.anims[name];
  const cfg = $(".slotcfg", card);
  cfg.innerHTML = `
    <div class="row"><b>Clip “${SLOT[name]}”</b><span class="muted">${an.frames} frame · ${Math.round(an.fps)} fps · ${an.width}×${an.height}px</span></div>
    <div class="row"><label>Cắt từ</label><input type="number" step="0.1" min="0" class="ts"><label>đến</label><input type="number" step="0.1" min="0" class="te"><span class="muted">giây (0 = hết clip)</span></div>
    <div class="row"><label><input type="checkbox" class="al"> Tự tìm đoạn lặp mượt</label></div>
    <div class="row"><label><input type="checkbox" class="pp"> Chạy tới rồi lui (khi chỗ lặp bị giật)</label></div>
    <div class="row"><label>To / nhỏ riêng clip này</label><input type="range" min="0.5" max="1.5" step="0.05" class="sc"><output></output></div>
    <div class="row"><button class="small apply">Áp dụng cắt</button><button class="ghost small replace">Thay clip…</button><button class="ghost small danger rm">Xóa clip</button></div>`;
  const ts = $(".ts", cfg), te = $(".te", cfg), al = $(".al", cfg), apply = $(".apply", cfg);
  ts.value = an.trim_start; te.value = an.trim_end; al.checked = an.auto_loop;
  const dirty = () => apply.classList.toggle("primary", +ts.value !== an.trim_start || +te.value !== an.trim_end || al.checked !== an.auto_loop);
  for (const i of [ts, te, al]) i.addEventListener("input", dirty);
  apply.onclick = () => importClips(card, a, [[name, clipForm(an, null, { trim_start: +ts.value || 0, trim_end: +te.value || 0, auto_loop: al.checked })]]);
  const pp = $(".pp", cfg);
  pp.checked = an.loop === "pingpong";
  pp.onchange = () => { an.loop = pp.checked ? "pingpong" : "loop"; scheduleSave(); };
  const sc = $(".sc", cfg);
  writeInput(sc, an.scale);
  sc.oninput = () => { an.scale = +sc.value; writeInput(sc, an.scale); scheduleSave(); };
  $(".replace", cfg).onclick = () => $(`.slot[data-anim=${name}] input`, card).click();
  $(".rm", cfg).onclick = async () => {
    if (!confirm(`Xóa clip “${SLOT[name]}”?`)) return;
    st.slot = null;
    setProject(await api("DELETE", `/api/projects/${P.id}/animals/${a.id}/anims/${name}`));
  };
  if (st.tab === "key") keyPreview(card, a);
}

// ---- motion tab
function buildMotion(card, a) {
  const sel = $(".preset", card);
  sel.add(new Option("— chọn loài để đặt nhanh —", ""));
  for (const [k, p] of Object.entries(PRESETS)) if (k !== "other") sel.add(new Option(`${p.icon} ${p.label}`, k));
  sel.onchange = () => {
    if (!sel.value) return;
    applyPreset(a, sel.value);
    toast(`Đã đặt kiểu chạy giống ${PRESETS[sel.value].label.toLowerCase()}`);
    scheduleSave();
    refreshCard(a);
  };
  const fb = $(".facing", card);
  const faceText = () => (fb.textContent = a.facing === "left" ? "← trái" : "phải →");
  faceText();
  fb.onclick = () => { a.facing = a.facing === "left" ? "right" : "left"; faceText(); scheduleSave(); };
  for (const [cls, fn] of [[".spd", setSpeed], [".act", setActivity], [".shy", setShy]]) {
    $(cls, card).addEventListener("input", e => {
      fn(a, +e.target.value);
      for (const inp of $$(".tab[data-tab=motion] [data-a]", card)) writeInput(inp, getPath(a, inp.dataset.a));
      scheduleSave();
    });
  }
  syncSimple(card, a);
}

function syncSimple(card, a) {
  $(".spd", card).value = speedLevel(a);
  $(".act", card).value = activityLevel(a);
  $(".shy", card).value = shyLevel(a);
}

// ---- key tab
function sameKey(u, k) {
  return Object.keys(KEY_DEFAULT).every(f => (typeof k[f] === "number" ? Math.abs(u[f] - k[f]) < 1e-6 : u[f] === k[f]));
}
const keyedClips = a => ANIMS.filter(n => hasClip(a, n) && a.anims[n].src);
// clips imported with other key settings than the current ones (unknown = assume up to date)
const staleClips = a => keyedClips(a).filter(n => a.anims[n].key_used && !sameKey(a.anims[n].key_used, a.key));

function updateKeyState(card, a) {
  const stale = staleClips(a), n = keyedClips(a).length;
  const s = $(".keystate", card), b = $(".keyapply", card);
  s.classList.toggle("dirty", stale.length > 0);
  b.classList.toggle("dirty", stale.length > 0);
  b.disabled = n === 0;
  if (!n) { s.textContent = "Upload clip ở tab Clip trước."; b.textContent = "Áp dụng"; }
  else if (stale.length) {
    s.textContent = `Đã chỉnh nhưng chưa áp dụng cho ${stale.length}/${n} clip. Video vẫn dùng bản tách nền cũ cho tới khi bấm Áp dụng.`;
    b.textContent = `Áp dụng cho ${stale.length} clip`;
  } else { s.textContent = `✓ ${n} clip đang dùng thông số này.`; b.textContent = "Tách nền lại tất cả clip"; }
  const tab = $(".tabs button[data-tab=key]", card);
  tab.querySelector(".dot")?.remove();
  if (stale.length) tab.insertAdjacentHTML("beforeend", `<i class="dot"></i>`);
}

function buildKey(card, a) {
  updateKeyState(card, a);
  $(".keyprev", card).classList.add("checker");
  $(".keyapply", card).onclick = () => {
    const stale = staleClips(a);
    importClips(card, a, (stale.length ? stale : keyedClips(a)).map(n => [n, clipForm(a.anims[n], null)]));
  };
  $(".keyreset", card).onclick = () => {
    a.key = { ...KEY_DEFAULT };
    for (const inp of $$(".tab[data-tab=key] [data-a]", card)) writeInput(inp, getPath(a, inp.dataset.a));
    keyPreview(card, a);
    updateKeyState(card, a);
    scheduleSave();
  };
}

let keyTimer = null;
function keyPreview(card, a) {
  clearTimeout(keyTimer);
  keyTimer = setTimeout(async () => {
    const st = uiOf(a.id);
    const name = st.slot && a.anims[st.slot]?.src ? st.slot : ANIMS.find(n => a.anims[n]?.src);
    if (!name) return;
    const an = a.anims[name];
    try {
      const r = await api("POST", `/api/projects/${P.id}/animals/${a.id}/anims/${name}/key-preview`,
        { key: a.key, trim_start: an.trim_start, trim_end: an.trim_end }, true);
      const img = $(".keyprev img", card);
      if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(await r.blob());
      img.title = `Xem thử clip “${SLOT[name]}”`;
    } catch (e) { toast(e.message, true); }
  }, 250);
}

// ---- sounds tab
function buildSounds(card, a) {
  bindDrop($(".sounds", card), async files => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    await saveNow();
    const p = await api("POST", `/api/projects/${P.id}/animals/${a.id}/sounds`, fd);
    toast(`Đã thêm ${files.length} tiếng kêu`);
    setProject(p);
  });
  const ul = $(".soundlist", card);
  for (const s of a.sounds) {
    const li = document.createElement("li");
    li.innerHTML = `<button class="ghost small play">▶</button><span></span><button class="ghost small danger">✕</button>`;
    $("span", li).textContent = s.split("/").pop();
    $(".play", li).onclick = () => new Audio(`/projects/${P.id}/${s}`).play();
    $(".danger", li).onclick = async () => setProject(await api("DELETE", `/api/projects/${P.id}/animals/${a.id}/sounds`, { file: s }));
    ul.appendChild(li);
  }
  if (!a.sounds.length) ul.innerHTML = `<li class="muted">Chưa có tiếng kêu.</li>`;
}

function bindDrop(label, onFiles) {
  const input = $("input[type=file]", label);
  const run = async files => {
    if (!files.length) return;
    label.classList.add("busy");
    try { await onFiles(files); } catch (e) { toast(e.message, true); } finally { label.classList.remove("busy"); }
  };
  input.addEventListener("change", () => { run([...input.files]); input.value = ""; });
  label.addEventListener("dragover", e => { e.preventDefault(); label.classList.add("over"); });
  label.addEventListener("dragleave", () => label.classList.remove("over"));
  label.addEventListener("drop", e => {
    e.preventDefault();
    label.classList.remove("over");
    run([...e.dataTransfer.files]);
  });
}

// ---- add animal
function buildPresetPicker() {
  const box = $("#presetPicker .pbtns");
  for (const [k, p] of Object.entries(PRESETS)) {
    const b = document.createElement("button");
    b.innerHTML = `<span>${p.icon}</span>${p.label}`;
    b.onclick = () => addAnimal(k);
    box.appendChild(b);
  }
}

async function addAnimal(key) {
  let name = PRESETS[key].name;
  if (!name) name = prompt("Tên con vật", "con vật");
  if (!name) return;
  await saveNow();
  const p = await api("POST", `/api/projects/${P.id}/animals`, { name });
  const a = p.animals.at(-1);
  applyPreset(a, key);
  $("#presetPicker").hidden = true;
  selectedAnimal = a.id;
  setProject(p);
  await saveNow();
  $(`.animal[data-id="${a.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  toast(`Đã thêm ${name}. Kéo clip idle / walk / run vào 3 ô.`);
}

// ------------------------------------------------------------------ stage: live preview ---
// The server builds a short timeline with the same engine as the real render; the browser
// samples it every frame and draws sprite sheets, so the preview moves like the video.
const cv = $("#canvas");
const ctx = cv.getContext("2d");
let drag = null;
const live = { tl: null, t: 0, playing: true, seed: 1, last: 0, sheets: {}, hits: [], soundIdx: 0, req: 0 };

function loadBackground() {
  const img = new Image();
  img.onload = () => { bgImg = img; };
  img.src = `/api/projects/${P.id}/background.jpg?t=${Date.now()}`;
}

async function refreshLive() {
  if (!P) return;
  const req = ++live.req;
  loadSheets();
  try {
    const tl = await api("POST", `/api/projects/${P.id}/live`, { seconds: 180, seed: live.seed });
    if (req !== live.req) return;
    for (const tr of tl.tracks) { tr.starts = tr.segs.map(s => s[0]); tr.cur = 0; }
    live.tl = tl;
    if (live.t >= tl.duration) live.t = 0;
    live.soundIdx = tl.sounds.findIndex(s => s[0] > live.t);
    if (live.soundIdx < 0) live.soundIdx = tl.sounds.length;
  } catch (_) {}
}

function loadSheets() {
  for (const a of P.animals) {
    for (const name of ANIMS) {
      if (!hasClip(a, name)) continue;
      const key = `${a.id}/${name}`, ver = animVer(a.anims[name]);
      if (live.sheets[key]?.ver === ver) continue;
      const entry = { ver };
      live.sheets[key] = entry;
      fetch(`/api/projects/${P.id}/animals/${a.id}/anims/${name}/sheet?v=${ver}`).then(async r => {
        if (!r.ok) return;
        const h = k => +r.headers.get(k);
        const info = { cols: h("X-Cols"), cw: h("X-Cell-W"), ch: h("X-Cell-H"), n: h("X-Frames") };
        info.bmp = await createImageBitmap(await r.blob());
        Object.assign(entry, info);
      }).catch(() => {});
    }
  }
}

function trapPos(s, a) {
  if (a <= 0) return s;
  s = clamp(s, 0, 1);
  const vmax = 1 / (1 - a);
  if (s < a) return 0.5 * vmax * s * s / a;
  if (s > 1 - a) { const r = 1 - s; return 1 - 0.5 * vmax * r * r / a; }
  return 0.5 * vmax * a + vmax * (s - a);
}
function resolveAnim(a, want) {
  const order = { idle: ["idle", "walk", "run"], walk: ["walk", "run", "idle"], run: ["run", "walk", "idle"] }[want];
  return order.find(n => hasClip(a, n));
}
function frameIndex(an, phase) {
  const n = an.frames;
  if (n <= 1) return 0;
  let p = Math.floor(phase);
  if (an.loop === "pingpong") {
    const period = 2 * (n - 1);
    p = ((p % period) + period) % period;
    return p < n ? p : period - p;
  }
  return ((p % n) + n) % n;
}
// reference px per stored sprite px (same as SpriteBank / sprite_ref_box on the server)
function unitOf(a, refW) {
  const ref = hasClip(a, "idle") ? a.anims.idle : a.anims[ANIMS.find(n => hasClip(a, n))];
  return a.size_pct / 100 * refW / (ref.width / ref.px_scale);
}
function depthOf(y, refH) {
  if (!P.render.depth_scale) return 1;
  const y0 = P.area.y * refH, y1 = (P.area.y + P.area.h) * refH;
  return y1 > y0 ? lerp(0.75, 1.25, clamp((y - y0) / (y1 - y0), 0, 1)) : 1;
}

function sampleLive(t) {
  const out = [];
  for (const tr of live.tl.tracks) {
    const a = P.animals.find(x => x.id === tr.animal);
    const segs = tr.segs;
    if (!a || !a.enabled || !segs.length) continue;
    let i = tr.cur;
    if (!(segs[i] && segs[i][0] <= t && t < segs[i][1])) {
      let lo = 0, hi = segs.length;
      while (lo < hi) { const m = (lo + hi) >> 1; if (tr.starts[m] <= t) lo = m + 1; else hi = m; }
      i = tr.cur = Math.max(0, lo - 1);
    }
    const [t0, t1, kind, x0, y0, cx, cy, x1, y1, anim, face0, accel, phase0] = segs[i];
    if (kind === "hidden") continue;
    const u = clamp((t - t0) / Math.max(t1 - t0, 1e-6), 0, 1);
    let x = x0, y = y0, want = "idle", face = face0, squash = 1;
    if (kind === "move") {
      const f = trapPos(u, accel), v = 1 - f;
      x = v * v * x0 + 2 * v * f * cx + f * f * x1;
      y = v * v * y0 + 2 * v * f * cy + f * f * y1;
      want = anim;
    } else if (kind === "turn") {
      squash = Math.max(0.15, Math.abs(Math.cos(Math.PI * u)));
      if (u >= 0.5) face = -face0;
    }
    const name = resolveAnim(a, want);
    if (!name) continue;
    const an = a.anims[name];
    out.push({ a, name, an, x, y, face, squash, frame: frameIndex(an, (phase0 + t - t0) * an.fps) });
  }
  return out.sort((p, q) => p.y - q.y);
}

function stageSize() {
  const r = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  return [cv.width, cv.height];
}

function drawStage() {
  if (!P) return;
  const [W, H] = stageSize();
  const dpr = window.devicePixelRatio || 1;
  ctx.clearRect(0, 0, W, H);
  if (bgImg) ctx.drawImage(bgImg, 0, 0, W, H);
  const ar = P.area;
  const x = ar.x * W, y = ar.y * H, w = ar.w * W, h = ar.h * H;
  ctx.fillStyle = drag ? "rgba(243,179,61,0.15)" : "rgba(243,179,61,0.05)";
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = "#f3b33d";
  ctx.lineWidth = 2 * dpr;
  ctx.setLineDash([8 * dpr, 6 * dpr]);
  ctx.strokeRect(x, y, w, h);
  ctx.setLineDash([]);
  ctx.fillStyle = "#f3b33d";
  for (const [hx, hy] of corners()) ctx.fillRect(hx * W - 6 * dpr, hy * H - 6 * dpr, 12 * dpr, 12 * dpr);
  ctx.font = `${12 * dpr}px Segoe UI`;
  ctx.fillText("Vùng chân con vật đi được", x + 8 * dpr, y + 18 * dpr);

  live.hits = [];
  const ready = live.tl && P.animals.some(a => a.enabled && ANIMS.some(n => hasClip(a, n)));
  if (!ready) {
    ctx.fillStyle = "rgba(0,0,0,.55)";
    ctx.fillRect(0, H / 2 - 22 * dpr, W, 44 * dpr);
    ctx.fillStyle = "#fff";
    ctx.textAlign = "center";
    ctx.font = `${14 * dpr}px Segoe UI`;
    ctx.fillText("Thêm con vật và upload clip để xem chuyển động ở đây", W / 2, H / 2 + 5 * dpr);
    ctx.textAlign = "start";
    return;
  }
  const [refW, refH] = live.tl.ref;
  const k = W / refW;
  for (const s of sampleLive(live.t)) {
    const sheet = live.sheets[`${s.a.id}/${s.name}`];
    if (!sheet?.bmp) continue;
    const unit = unitOf(s.a, refW) * k * depthOf(s.y, refH) * s.an.scale / s.an.px_scale;
    const sw = s.an.width * unit, sh = s.an.height * unit;
    const fx = s.x * k, fy = s.y * k;
    if (P.render.shadow && P.render.shadow_opacity > 0) {
      const shh = Math.max(3, sh * 0.14);
      ctx.save();
      ctx.filter = `blur(${Math.max(1, shh * 0.45)}px)`;
      ctx.fillStyle = `rgba(0,0,0,${P.render.shadow_opacity})`;
      ctx.beginPath();
      ctx.ellipse(fx, fy - shh * 0.1, Math.max(2, sw * 0.4), shh / 2, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
    const flip = s.face !== (s.a.facing === "left" ? -1 : 1);
    const fi = Math.min(s.frame, sheet.n - 1);
    ctx.save();
    ctx.translate(fx, fy);
    ctx.scale((flip ? -1 : 1) * s.squash, 1);
    ctx.drawImage(sheet.bmp, (fi % sheet.cols) * sheet.cw, Math.floor(fi / sheet.cols) * sheet.ch, sheet.cw, sheet.ch,
      -sw / 2, -sh, sw, sh);
    ctx.restore();
    if (s.a.id === selectedAnimal) {
      ctx.strokeStyle = "rgba(79,176,255,.9)";
      ctx.lineWidth = 1.5 * dpr;
      ctx.setLineDash([4 * dpr, 3 * dpr]);
      ctx.strokeRect(fx - sw / 2 - 3 * dpr, fy - sh - 3 * dpr, sw + 6 * dpr, sh + 6 * dpr);
      ctx.setLineDash([]);
    }
    live.hits.push({ id: s.a.id, x0: (fx - sw / 2) / W, y0: (fy - sh) / H, x1: (fx + sw / 2) / W, y1: fy / H });
  }
}

// animated thumbnails in the clip slots (shown as in the source clip, not flipped)
function drawSlots(now) {
  for (const c of $$(".slot canvas")) {
    const a = P.animals.find(x => x.id === c.dataset.aid);
    const an = a?.anims[c.dataset.anim];
    const sheet = live.sheets[`${c.dataset.aid}/${c.dataset.anim}`];
    if (!an || !sheet?.bmp) continue;
    const g = c.getContext("2d");
    g.clearRect(0, 0, c.width, c.height);
    const fi = Math.min(frameIndex(an, now / 1000 * an.fps), sheet.n - 1);
    const s = Math.min((c.width - 8) / sheet.cw, (c.height - 8) / sheet.ch);
    const w = sheet.cw * s, h = sheet.ch * s;
    g.drawImage(sheet.bmp, (fi % sheet.cols) * sheet.cw, Math.floor(fi / sheet.cols) * sheet.ch, sheet.cw, sheet.ch,
      (c.width - w) / 2, (c.height - h) / 2, w, h);
  }
}

function playLiveSounds() {
  const snd = live.tl.sounds;
  while (live.soundIdx < snd.length && snd[live.soundIdx][0] <= live.t) {
    const [, aid, file, vol] = snd[live.soundIdx++];
    const a = P.animals.find(x => x.id === aid);
    if (!$("#liveSound").checked || !a?.enabled || !a.sound_enabled) continue;
    const au = new Audio(`/projects/${P.id}/${file}`);
    au.volume = clamp(vol, 0, 1);
    au.play().catch(() => {});
  }
}

function tick(now) {
  const dt = Math.min(0.1, (now - (live.last || now)) / 1000);
  live.last = now;
  if (P) {
    if (live.playing && live.tl) {
      live.t += dt;
      if (live.t >= live.tl.duration) { live.t = 0; live.soundIdx = 0; }
      playLiveSounds();
    }
    drawStage();
    drawSlots(now);
  }
  requestAnimationFrame(tick);
}

function liveBtnText() { $("#liveBtn").textContent = live.playing ? "⏸ Tạm dừng" : "▶ Chạy tiếp"; }
$("#liveBtn").onclick = () => { live.playing = !live.playing; liveBtnText(); };
$("#liveSeed").onclick = () => { live.seed = Math.floor(Math.random() * 1e9); live.t = 0; refreshLive(); };
liveBtnText();

function corners() {
  const a = P.area;
  return [[a.x, a.y], [a.x + a.w, a.y], [a.x, a.y + a.h], [a.x + a.w, a.y + a.h]];
}

function pos(e) {
  const r = cv.getBoundingClientRect();
  return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
}
const hitAnimal = (px, py) => [...live.hits].reverse().find(h => px >= h.x0 && px <= h.x1 && py >= h.y0 && py <= h.y1);
function onCorner(px, py) {
  const r = cv.getBoundingClientRect();
  return corners().findIndex(([cx, cy]) => Math.abs(cx - px) < 12 / r.width && Math.abs(cy - py) < 12 / r.height);
}

cv.addEventListener("pointerdown", e => {
  if (!P) return;
  const [px, py] = pos(e);
  const ci = onCorner(px, py);
  const a = P.area;
  if (ci < 0) {
    const hit = hitAnimal(px, py);
    if (hit) { selectAnimal(hit.id, true); return; }
  }
  if (ci >= 0) drag = { mode: "corner", ci };
  else if (px > a.x && px < a.x + a.w && py > a.y && py < a.y + a.h) drag = { mode: "move", dx: px - a.x, dy: py - a.y };
  else drag = { mode: "new", x0: px, y0: py };
  cv.setPointerCapture(e.pointerId);
});
cv.addEventListener("pointermove", e => {
  if (!P) return;
  const [px, py] = pos(e).map(v => clamp(v, 0, 1));
  const a = P.area;
  if (!drag) {
    cv.style.cursor = onCorner(px, py) >= 0 ? "nwse-resize" : hitAnimal(px, py) ? "pointer"
      : (px > a.x && px < a.x + a.w && py > a.y && py < a.y + a.h) ? "move" : "crosshair";
    return;
  }
  if (drag.mode === "move") {
    a.x = clamp(px - drag.dx, 0, 1 - a.w);
    a.y = clamp(py - drag.dy, 0, 1 - a.h);
  } else {
    let x0, y0;
    if (drag.mode === "corner") {
      [x0, y0] = corners()[3 - drag.ci];
      drag = { mode: "new", x0, y0 };
    } else ({ x0, y0 } = drag);
    a.x = Math.min(x0, px); a.y = Math.min(y0, py);
    a.w = Math.max(Math.abs(px - x0), 0.02); a.h = Math.max(Math.abs(py - y0), 0.02);
  }
});
cv.addEventListener("pointerup", () => {
  if (drag) { drag = null; scheduleSave(); }
});
buildPresetPicker();
requestAnimationFrame(tick);

// ------------------------------------------------------------------ jobs --------------
const seenDone = new Set();
async function pollJobs() {
  try {
    const list = await api("GET", "/api/jobs");
    const box = $("#jobs");
    box.innerHTML = list.length ? "" : `<p class="hint">Chưa có công việc nào.</p>`;
    let newOutput = false;
    for (const j of list) {
      const el = document.createElement("div");
      el.className = "job " + j.status;
      const pct = (j.progress * 100).toFixed(1);
      const stage = { timeline: "tạo kịch bản", video: "render hình", audio: "trộn âm thanh", concat: "ghép file", thumbnail: "thumbnail", done: "xong" }[j.stage] || j.stage;
      let st = { queued: "Đang chờ", running: `${pct}% · ${stage}`, done: "✔ Xong", error: "✖ Lỗi", cancelled: "Đã hủy" }[j.status];
      if (j.status === "running" && j.fps) st += ` · ${j.fps} fps · còn ${fmtTime(j.eta)}`;
      if (j.status === "done") st += ` trong ${fmtTime(j.elapsed)} · seed ${j.seed}`;
      el.innerHTML = `<div><b></b><div class="st"></div></div><div class="btns"></div><div class="bar"><i style="width:${j.status === "done" ? 100 : pct}%"></i></div>`;
      $("b", el).textContent = j.title;
      $(".st", el).textContent = st;
      const btns = $(".btns", el);
      if (j.status === "queued" || j.status === "running") {
        const b = document.createElement("button");
        b.className = "ghost small danger"; b.textContent = "Hủy";
        b.onclick = () => api("DELETE", `/api/jobs/${j.id}`).then(pollJobs);
        btns.appendChild(b);
      } else {
        if (j.status === "done" && j.file) {
          const b = document.createElement("button");
          b.className = "ghost small"; b.textContent = "▶ Xem";
          b.onclick = () => play(j.folder ? `/output/${j.folder}/${j.file}` : `/output/${j.file}`);
          btns.appendChild(b);
        }
        const x = document.createElement("button");
        x.className = "ghost small"; x.textContent = "✕";
        x.onclick = () => api("DELETE", `/api/jobs/${j.id}`).then(pollJobs);
        btns.appendChild(x);
      }
      if (j.error) {
        const e = document.createElement("div");
        e.className = "err"; e.textContent = j.error;
        el.appendChild(e);
      }
      box.appendChild(el);
      if (j.status === "done" && !seenDone.has(j.id)) {
        if (seenDone.size || pollJobs.primed) {
          if (j.kind === "preview") play(`/output/${j.folder}/${j.file}`);
          else toast("Đã tạo xong " + j.file);
          newOutput = true;
        }
        seenDone.add(j.id);
      }
    }
    pollJobs.primed = true;
    if (newOutput) loadOutputs();
  } catch (_) {}
}

function play(url) {
  $("#player").hidden = false;
  const v = $("#video");
  v.src = url;
  v.play().catch(() => {});
  v.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function loadOutputs() {
  const list = await api("GET", "/api/outputs");
  const box = $("#outputs");
  box.innerHTML = list.length ? "" : `<p class="hint">Chưa có video nào.</p>`;
  for (const o of list) {
    const el = document.createElement("div");
    el.className = "out";
    el.innerHTML = `<img alt=""><div><b></b><br><span class="muted"></span><br><a target="_blank">Tải / mở</a></div>`;
    $("img", el).src = `/output/${encodeURIComponent(o.thumbnail)}`;
    $("img", el).onclick = () => play(`/output/${encodeURIComponent(o.file)}`);
    $("b", el).textContent = o.file;
    $(".muted", el).textContent = `${o.duration} · ${o.width}×${o.height}@${o.fps} · ${o.size_mb} MB · seed ${o.seed}`;
    $("a", el).href = `/output/${encodeURIComponent(o.file)}`;
    box.appendChild(el);
  }
}

// ------------------------------------------------------------------ wiring ------------
for (const el of $$("[data-bind]")) {
  const ev = el.type === "range" ? "input" : "change";
  el.addEventListener(ev, () => {
    setPath(P, el.dataset.bind, readInput(el));
    writeInput(el, getPath(P, el.dataset.bind));
    if (el.dataset.bind === "render.duration") $("#durPreset").value = [...$("#durPreset").options].some(o => o.value === P.render.duration) ? P.render.duration : "";
    scheduleSave();
  });
}
$("#durPreset").onchange = e => {
  if (!e.target.value) { $("#durCustom").focus(); return; }
  P.render.duration = e.target.value;
  $("#durCustom").value = e.target.value;
  scheduleSave();
};
$("#resSel").onchange = e => {
  const [w, h] = e.target.value.split("x").map(Number);
  P.render.width = w; P.render.height = h;
  $("#stage").style.aspectRatio = `${w} / ${h}`;
  scheduleSave();
  loadBackground();
};
$("#seedRnd").onclick = () => {
  P.render.seed = Math.floor(Math.random() * 2 ** 31);
  writeInput($("[data-bind='render.seed']"), P.render.seed);
  scheduleSave();
};
$("#projSel").onchange = async e => { if (saveTimer) await saveNow(); openProject(e.target.value); };
$("#projNew").onclick = async () => {
  const name = prompt("Tên project mới", "Mouse TV");
  if (!name) return;
  const p = await api("POST", "/api/projects", { name });
  await loadProjects(p.id);
};
$("#projDel").onclick = async () => {
  if (!confirm(`Xóa project "${P.name}" cùng toàn bộ asset? (video đã render trong output vẫn giữ)`)) return;
  await api("DELETE", `/api/projects/${P.id}`);
  localStorageSet("project", "");
  await loadProjects();
};
$("#animalAdd").onclick = () => { const pk = $("#presetPicker"); pk.hidden = !pk.hidden; };
bindDrop($("[data-upload=background]"), async files => {
  const drop = $("[data-upload=background]");
  drop.classList.add("busy");
  try {
    const r = await api("POST", `/api/projects/${P.id}/background`, (() => { const f = new FormData(); f.append("file", files[0]); return f; })());
    toast(`Đã nhập nền ${r.width}×${r.height}`);
    setProject(r.project);
  } finally { drop.classList.remove("busy"); }
});
bindDrop($("[data-upload=ambience]"), async files => {
  const fd = new FormData();
  fd.append("file", files[0]);
  setProject(await api("POST", `/api/projects/${P.id}/ambience`, fd));
  toast("Đã nhập âm nền");
});
$("#ambDel").onclick = async () => setProject(await api("DELETE", `/api/projects/${P.id}/ambience`));

async function startJob(url, body) {
  if (saveTimer) await saveNow();
  try {
    await api("POST", url, body);
    toast("Đã thêm vào hàng đợi");
    pollJobs();
  } catch (e) { toast(e.message, true); }
}
$("#btnPreview").onclick = () => startJob(`/api/projects/${P.id}/preview`, { seconds: 60 });
$("#btnRender").onclick = () => startJob(`/api/projects/${P.id}/render`);
$("#btnBatch").onclick = () => startJob(`/api/projects/${P.id}/batch`, { count: parseInt($("#batchN").value, 10) || 1 });
$("#btnOpenOut").onclick = () => api("POST", "/api/open-output");

(async function init() {
  try {
    const s = await api("GET", "/api/system");
    $("#sys").textContent = s.encoder ? `FFmpeg ✓ · encoder ${s.encoder} · ${s.workers} luồng render` : "⚠ " + s.ffmpeg;
  } catch (_) {}
  await loadProjects();
  await pollJobs();
  loadOutputs();
  setInterval(pollJobs, 1000);
})();
