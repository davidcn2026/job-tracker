/* 投递记录 · 前端逻辑
 *
 * 设计约束（详见交付说明）：
 *  1. 零依赖、零构建：原生 fetch + DOM API，浏览器直接跑
 *  2. 一律同源请求 /api/v1，不涉及 CORS
 *  3. 所有用户数据都用 textContent 写入，绝不拼接 innerHTML，避免 JD 原文里的脚本被执行
 *  4. 后端暂不支持筛选/分页参数，所以一次性取 100 条，在前端筛选和分页
 */

"use strict";

/* 前端版本标记。
 * 排查"改了代码但界面没变"时，第一步就是确认浏览器到底加载了哪一版：
 * 打开控制台，看这行日志的版本号对不对。 */
const APP_VERSION = "2026-11-25 15:40（含简历导入）";

const API = "/api/v1";
const TOKEN_KEY = "jt_token";
const USER_KEY = "jt_user";
const FETCH_LIMIT = 100; // 后端 page_size 上限

/* ---------- 状态徽章 / 建议徽章的类名映射 ---------- */
const STATUS_CLASS = {
  待投: "st-pending",
  已投: "st-sent",
  预约面试: "st-scheduled",
  已面试: "st-interviewed",
  已挂: "st-rejected",
};

const VERDICT_CLASS = {
  推荐投递: "vd-recommend",
  可考虑投递: "vd-consider",
  可以投递: "vd-apply",
  不建议投递: "vd-avoid",
};

/* ---------- 全局状态 ---------- */
const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  user: null,
  items: [],
  statusFilter: "",
  query: '',
  groupBy: 'score',
  activeGroup: 'all',
  editId: null,
  analyzing: new Set(),
  pollTimer: null,
  pollCount: 0,
};

/* ---------- 小工具 ---------- */
const $ = (sel) => document.querySelector(sel);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

let toastTimer = null;
function toast(message, isError = false) {
  const box = $("#toast");
  box.textContent = message;
  box.className = isError ? "toast error" : "toast";
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 2800);
}

function errorText(payload, fallback) {
  if (!payload) return fallback;
  if (typeof payload === "string") return fallback;
  // 统一响应体：{code, message, data}
  if (payload.message) return payload.message;
  // FastAPI 原生校验错误：{detail: [...]}
  if (Array.isArray(payload.detail)) {
    const first = payload.detail[0];
    if (first && first.msg) return `${first.msg}`;
  }
  if (typeof payload.detail === "string") return payload.detail;
  return fallback;
}

/* ---------- 网络层 ---------- */
class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = "GET", body, formData, auth = true } = {}) {
  const headers = {};
  let requestBody;

  if (formData) {
    // 传 FormData 时绝不能自己设 Content-Type ——
    // 浏览器要在里面写 multipart 的 boundary，手写会覆盖掉、后端解不出来
    requestBody = formData;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    requestBody = JSON.stringify(body);
  }

  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;

  let resp;
  try {
    resp = await fetch(API + path, { method, headers, body: requestBody });
  } catch {
    throw new ApiError(0, "网络不可用，请检查连接");
  }

  let payload = null;
  const text = await resp.text();
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = { detail: text }; }
  }

  if (resp.status === 401) {
    logout(false);
    // 保留后端的具体原因（"登录已过期，请重新登录" / "未认证或登录已失效"），
    // 别统一换成一句笼统的"登录已失效"——用户分不清是过期还是在别处被顶掉
    throw new ApiError(401, errorText(payload, "登录已失效，请重新登录"));
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, errorText(payload, `请求失败（HTTP ${resp.status}）`));
  }
  return payload;
}

/* ---------- 视图 ---------- */
function hideBoot() {
  const boot = $("#view-boot");
  if (boot) boot.hidden = true;
}

function showApp() {
  hideBoot();
  $("#view-assistant").hidden = true;
  $("#view-login").hidden = true;
  $("#view-app").hidden = false;
  $("#whoami").textContent = state.user ? state.user.name : "";
}

function showLogin() {
  hideBoot();
  $("#view-assistant").hidden = true;
  $("#view-app").hidden = true;
  $("#view-login").hidden = false;
  setAuthMode("login");
  $("#login-form").reset();
  $("#register-form").reset();
}

/* 清空"列表视图"的临时状态。
 * 登出 / 新登录时必须调用：
 *   1. 否则同一个浏览器换账号登录，会继承上一个用户留下的筛选条件和页码
 *   2. 这是 bug，也是跨用户的状态泄漏
 * 注意：筛选本身是"临时视图状态"，不是用户偏好，所以不跨会话保留。 */
function resetUiState() {
  state.statusFilter = "";
  state.query = "";
  state.groupBy = "score";
  state.activeGroup = "all";
  state.items = [];
  state.analyzing.clear();
  state.editId = null;

  const select = $("#filter-status");
  if (select) select.value = "";

  const search = $("#q-input");
  if (search) search.value = "";

  const groupBy = $("#group-by");
  if (groupBy) groupBy.value = "score";

  const dialog = $("#dlg-job");
  if (dialog && dialog.open) dialog.close();
}

function logout(showToast = true) {
  state.token = "";
  state.user = null;
  resetUiState();
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  showLogin();
  if (showToast) toast("已登出");
}

/* ---------- 登录 ---------- */
function afterAuth(data) {
  state.token = data.token;
  state.user = data.user;
  resetUiState(); // 新会话从干净状态开始，不继承上一次的筛选/页码
  localStorage.setItem(TOKEN_KEY, data.token);
  localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  showApp();
}

async function doLogin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const btn = $("#btn-login");
  const msg = $("#login-msg");
  const name = form.name.value.trim();
  const password = form.password.value;

  msg.hidden = true;
  btn.disabled = true;
  btn.textContent = "登录中…";

  try {
    const payload = await api("/auth/login", {
      method: "POST",
      body: { name, password },
      auth: false,
    });
    afterAuth(payload.data);
    await refresh();
  } catch (err) {
    msg.textContent = err.message;
    msg.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "登录";
  }
}

/* ---------- 注册（受限开放：需邀请码） ---------- */
async function doRegister(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const msg = $("#register-msg");
  const btn = $("#btn-register");

  const name = form.name.value.trim();
  const password = form.password.value;
  const password2 = form.password2.value;
  const code = form.code.value.trim();

  msg.hidden = true;

  // 前端先挡一次：两次密码不一致，不必浪费一次请求
  if (password !== password2) {
    msg.textContent = "两次输入的密码不一致";
    msg.hidden = false;
    return;
  }

  btn.disabled = true;
  btn.textContent = "注册中…";

  try {
    const payload = await api("/auth/register", {
      method: "POST",
      body: { name, password, code },
      auth: false,
    });
    // 注册接口直接返回 token，所以注册完就是登录状态
    afterAuth(payload.data);
    toast("注册成功");
    await refresh();
  } catch (err) {
    msg.textContent = err.message;
    msg.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "注册并登录";
  }
}

/* 登录 ↔ 注册 切换 */
function setAuthMode(mode) {
  const isRegister = mode === "register";
  $("#login-form").hidden = isRegister;
  $("#register-form").hidden = !isRegister;
  $("#login-msg").hidden = true;
  $("#register-msg").hidden = true;
  $("#btn-toggle-mode").textContent = isRegister
    ? "已有账号？返回登录"
    : "没有账号？用邀请码注册";
}

/* 有 JD 但没分数的岗位 = 后台正在分析，前端自动轮询等它出分。
 * 用户不需要点任何按钮。最多轮询 20 次（约 1 分钟），避免无限请求。 */
function schedulePendingPoll() {
  clearTimeout(state.pollTimer);

  const pending = state.items.some((job) => job.has_description && job.match_score == null);
  if (!pending) {
    state.pollCount = 0;
    return;
  }
  if (state.pollCount >= 20) return;

  state.pollCount += 1;
  state.pollTimer = setTimeout(() => refresh(true), 3000);
}

/* ---------- 数据加载 ---------- */
/* 把当前筛选条件拼成 query string。
 * 筛选在**服务端**做（后端已支持 status / source / q）：
 * 逻辑只有一份，数据涨到几百条也不用改前端。 */
function buildQuery() {
  const params = new URLSearchParams();
  params.set("page", "1");
  params.set("page_size", String(FETCH_LIMIT));
  if (state.statusFilter) params.set("status", state.statusFilter);
  if (state.query) params.set("q", state.query);
  return params.toString();
}

/* silent = true 用于后台轮询：不显示骨架屏，避免每次刷新闪一下 */
async function refresh(silent = false) {
  const list = $("#list");

  if (!silent) {
    list.replaceChildren();
    for (let i = 0; i < 3; i += 1) list.append(el("div", "skeleton"));
  }

  try {
    const payload = await api(`/jobs?${buildQuery()}`);
    state.items = payload.data.list || [];
    if (!silent) state.pollCount = 0;
    render();
  } catch (err) {
    if (!silent) {
      list.replaceChildren();
      list.append(el("p", "empty", err.message));
    }
  }
}

/* ---------- 渲染 ---------- */
/* 分组方式：按匹配度 / 按渠道。两者互斥，用工具栏的下拉切换。 */
/* 岗位按匹配度分层。
 * 分数区间与提示词里的分档完全一致——同一套标准，
 * 避免"模型说可以投、界面说别投"。 */
const SCORE_BANDS = [
  { key: "focus", label: "重点投递", min: 75, hint: "值得为它专门准备" },
  { key: "consider", label: "可考虑", min: 65, hint: "准备一下再投" },
  { key: "mass", label: "海投", min: 50, hint: "顺手投，别花太多精力" },
  { key: "skip", label: "不建议", min: 0, hint: "缺核心能力，先放一放" },
  { key: "none", label: "未分析", min: null, hint: "先点「AI 分析」拿到分数" },
];

/* 分组维度：匹配度 / 招聘渠道。二者互斥，用工具栏下拉切换。 */
const SOURCE_ORDER = ["Boss直聘", "本校", "自定义", "其他"];

function bandOf(job) {
  if (job.match_score == null) return "none";
  for (const band of SCORE_BANDS) {
    if (band.min !== null && job.match_score >= band.min) return band.key;
  }
  return "skip";
}

function sourceOf(job) {
  return SOURCE_ORDER.includes(job.source) ? job.source : "其他";
}

/* 一个岗位在当前分组维度下属于哪一组 */
function groupKeyOf(job) {
  return state.groupBy === "source" ? sourceOf(job) : bandOf(job);
}

/* 当前维度下的所有分组定义（含全部） */
function groupDefs() {
  if (state.groupBy === "source") {
    return SOURCE_ORDER.map((name) => ({ key: name, label: name }));
  }
  return SCORE_BANDS.map((band) => ({ key: band.key, label: band.label }));
}

/* 分数降序；未分析的排最后。同分时新录入的在前。 */
function sortByScore(jobs) {
  return [...jobs].sort((a, b) => {
    const sa = a.match_score == null ? -1 : a.match_score;
    const sb = b.match_score == null ? -1 : b.match_score;
    if (sb !== sa) return sb - sa;
    return b.id - a.id;
  });
}

/* 横向滚动的分组 Tab：全部 + 各组（空组不显示，省横向空间） */
function renderTabs(rows) {
  const bar = $("#tab-bar");
  bar.replaceChildren();

  const defs = groupDefs();
  const counts = new Map(defs.map((d) => [d.key, 0]));
  for (const job of rows) {
    const key = groupKeyOf(job);
    counts.set(key, (counts.get(key) || 0) + 1);
  }

  // 选中组已经空了（比如切了维度）→ 回到「全部」
  const keys = ["all", ...defs.filter((d) => counts.get(d.key) > 0).map((d) => d.key)];
  if (!keys.includes(state.activeGroup)) state.activeGroup = "all";

  const makeTab = (key, label, count) => {
    const tab = el("button", `tab${state.activeGroup === key ? " active" : ""}`,
      `${label} ${count}`);
    tab.type = "button";
    tab.dataset.key = key;
    return tab;
  };

  bar.append(makeTab("all", "全部", rows.length));
  for (const def of defs) {
    const count = counts.get(def.key) || 0;
    if (count > 0) bar.append(makeTab(def.key, def.label, count));
  }
}

function render() {
  const list = $("#list");
  const rows = state.items;          // 筛选已在服务端做（status / q）

  renderTabs(rows);

  const visible = state.activeGroup === "all"
    ? rows
    : rows.filter((job) => groupKeyOf(job) === state.activeGroup);

  list.replaceChildren();

  if (visible.length === 0) {
    list.append(el("p", "empty",
      state.query || state.statusFilter
        ? "没有符合条件的岗位，换个条件试试"
        : "还没有记录，点「+ 新增」开始"));
  } else {
    // 默认按分数从高到低：用户最该先看的排在最上面
    for (const job of sortByScore(visible)) list.append(jobCard(job));
  }

  /* 筛选提示：让"正在筛选/搜索"这件事可见，避免误以为数据丢了 */
  const hint = $("#filter-hint");
  const active = [];
  if (state.query) active.push(`搜索「${state.query}」`);
  if (state.statusFilter) active.push(`状态「${state.statusFilter}」`);

  if (active.length) {
    hint.hidden = false;
    $("#filter-hint-text").textContent = `${active.join(" · ")}，共 ${rows.length} 条`;
  } else {
    hint.hidden = true;
  }

  schedulePendingPoll();
}
function jobCard(job) {
  const card = el("div", "card");
  card.dataset.id = String(job.id);

  /* 标题行 */
  const head = el("div", "card-head");
  const title = el("div", "card-title");
  title.append(el("div", "company", job.company));
  title.append(el("div", "position", job.position));
  head.append(title);
  head.append(el("span", `badge ${STATUS_CLASS[job.status] || "st-pending"}`, job.status));
  card.append(head);

  /* 元信息 */
  const meta = el("div", "card-meta");

  if (job.salary_min != null || job.salary_max != null) {
    const lo = job.salary_min ?? "?";
    const hi = job.salary_max ?? "?";
    const note = job.salary_note ? `·${job.salary_note}` : "";
    meta.append(el("span", null, `${lo}-${hi}k${note}`));
  }
  if (job.source) {
    meta.append(el("span", null,
      job.source_detail ? `${job.source}·${job.source_detail}` : job.source));
  }
  if (job.published_at) meta.append(el("span", null, `发布 ${job.published_at}`));
  if (job.next_interview_at) {
    meta.append(el("span", null, `面试 ${formatDateTime(job.next_interview_at)}`));
  }
  // 两类链接分开显示：看 JD（详情）和真正投递（入口）
  if (job.url) {
    const link = el("a", "link-jd", "岗位详情");
    link.href = job.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    meta.append(link);
  }
  if (job.apply_url) {
    const apply = el("a", "link-apply", "去投递 ↗");
    apply.href = job.apply_url;
    apply.target = "_blank";
    apply.rel = "noopener noreferrer";
    meta.append(apply);
  }
  if (meta.childNodes.length) card.append(meta);

  /* AI 结论（分数与档位在列表响应里就有，详情按需加载） */
  if (job.match_score != null) {
    const row = el("div", "card-meta");
    row.append(el("span", "badge score", `${job.match_score} 分`));
    if (job.verdict) {
      row.append(el("span", `badge ${VERDICT_CLASS[job.verdict] || "vd-apply"}`, job.verdict));
    }
    if (job.analyzed_at) {
      row.append(el("span", null, `分析于 ${formatDateTime(job.analyzed_at)}`));
    }
    card.append(row);
  } else if (job.has_description) {
    // 有 JD 但没分数 = 后台正在分析（或失败待重试），给个明确的状态
    const row = el("div", "card-meta");
    row.append(el("span", "badge score", "分析中…"));
    card.append(row);
  }

  /* 操作按钮 */
  const actions = el("div", "card-actions");

  // 打分是幂等的：打过分的岗位不再提供"重新分析"，只有修改 JD 才会重算。
  // 只有在"有 JD 但没分数"时才显示按钮——那是自动分析失败后的兜底入口。
  if (job.match_score == null && job.has_description) {
    const btnAnalyze = el("button", "ghost small", "分析");
    btnAnalyze.disabled = state.analyzing.has(job.id);
    btnAnalyze.addEventListener("click", () => analyzeJob(job.id));
    actions.append(btnAnalyze);
  }

  const btnEdit = el("button", "ghost small", "编辑");
  btnEdit.addEventListener("click", () => openForm(job));

  const btnDelete = el("button", "ghost small", "删除");
  btnDelete.addEventListener("click", () => removeJob(job));

  actions.append(btnEdit, btnDelete);
  card.append(actions);

  /* 分析详情：原生 details，内容按需懒加载 */
  if (job.analyzed_at) card.append(analysisBlock(job));

  return card;
}

function parseAnalysis(raw) {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function renderAnalysisParts(data) {
  const nodes = [];
  if (data.summary) nodes.push(el("p", "summary", data.summary));

  const sections = [
    ["核心缺口（blocking）", data.blocking_gaps, "blocking"],
    ["其他缺口", data.gaps],
    ["已满足", data.matched],
  ];

  for (const [label, items, extra] of sections) {
    if (!Array.isArray(items) || items.length === 0) continue;
    nodes.push(el("h4", null, label));
    const ul = el("ul");
    if (extra) ul.className = extra;
    for (const item of items) ul.append(el("li", null, item));
    nodes.push(ul);
  }
  return nodes;
}

/* 列表接口不返回 analysis 全文（避免响应体过大），
 * 所以详情在用户展开时才请求单条详情接口。 */
function analysisBlock(job) {
  const box = el("details", "analysis");
  box.append(el("summary", null, "查看分析详情"));
  const body = el("div");
  box.append(body);

  const immediate = parseAnalysis(job.analysis);
  if (immediate) {
    body.append(...renderAnalysisParts(immediate));
    return box;
  }

  let loaded = false;
  box.addEventListener("toggle", async () => {
    if (!box.open || loaded) return;
    loaded = true;
    body.replaceChildren(el("p", "empty", "加载中…"));
    try {
      const payload = await api(`/jobs/${job.id}`);
      const data = parseAnalysis(payload.data.analysis);
      body.replaceChildren();
      if (data) body.append(...renderAnalysisParts(data));
      else body.append(el("p", "empty", "这条记录还没有分析结果"));
    } catch (err) {
      loaded = false; // 允许重试
      body.replaceChildren(el("p", "empty", err.message));
    }
  });

  return box;
}

function formatDateTime(value) {
  if (!value) return "";
  const text = String(value).replace("T", " ");
  return text.slice(0, 16);
}

/* ---------- 分析 ---------- */
async function analyzeJob(id) {
  if (state.analyzing.has(id)) return;
  state.analyzing.add(id);
  render(); // 立刻把该卡片按钮切成「分析中…」并禁用，防连点（后端也有 429 兜底）

  try {
    const payload = await api(`/jobs/${id}/analyze`, { method: "POST" });
    const updated = payload.data;

    // 用返回的完整详情替换列表里的旧对象，再整体重绘（列表规模很小）
    const idx = state.items.findIndex((job) => job.id === id);
    if (idx >= 0) state.items[idx] = { ...state.items[idx], ...updated };

    toast(`${updated.verdict} · ${updated.match_score} 分`);
  } catch (err) {
    toast(err.message, true);
  } finally {
    state.analyzing.delete(id);
    render(); // 恢复按钮文字/可点状态，或展示新结果
  }
}

/* ---------- 截图导入 ---------- */
/* 流程：截图 → 上传 → 后端识别出草稿 → 预填表单 → 用户确认后才 POST /jobs。
 * 绝不让 AI 直接写库：模型会看错，错误数据静默进库比没有这个功能更糟。 */
async function importScreenshot(file) {
  if (!file) return;

  if (!file.type.startsWith("image/")) {
    toast("请选择图片文件（PNG / JPEG / WebP）", true);
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    toast("图片不能超过 10 MB", true);
    return;
  }

  const btn = $("#btn-shot");
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "识别中…";

  try {
    const formData = new FormData();
    formData.append("image", file);
    const payload = await api("/jobs/extract", { method: "POST", formData });
    const draft = payload.data || {};

    if (!draft.company && !draft.position) {
      toast("没能识别出岗位信息，换个截图试试", true);
      return;
    }

    openForm(null, draft);
    toast(`识别完成，请核对（信心 ${Math.round((draft.confidence ?? 0) * 100)}%）`);
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

/* ---------- 我的简历 ---------- */
/* 和截图导入同一原则：解析 → 用户核对 → 保存。
 * 解析可能错（扫描件、排版复杂、OCR 认错字），所以 upload 只填进编辑框，
 * 必须用户点「保存」才真正写进数据库。 */

function showProfileError(message) {
  const box = $("#profile-msg");
  box.textContent = message;
  box.hidden = false;
}

function updateProfileStatus(profile) {
  const box = $("#profile-status");
  if (profile && profile.chars) {
    box.className = "msg ok";
    box.textContent = `当前简历 ${profile.chars} 字，更新于 ${formatDateTime(profile.updated_at)}`;
  } else {
    box.className = "msg error";
    box.textContent = "还没有简历。没有简历时「AI 分析」会被拒绝。";
  }
  box.hidden = false;
}

async function openProfile() {
  $("#profile-msg").hidden = true;
  $("#profile-status").hidden = true;

  const form = $("#profile-form");
  form.reset();
  $("#dlg-profile").showModal();

  try {
    const payload = await api("/users/me/profile");
    const profile = payload.data;
    form.elements.text.value = profile.text || "";
    updateProfileStatus(profile);
  } catch (err) {
    showProfileError(err.message);
  }
}

async function importProfileFile(file) {
  if (!file) return;

  const btn = $("#btn-profile-upload");
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "解析中…";
  $("#profile-msg").hidden = true;

  try {
    const formData = new FormData();
    formData.append("file", file);
    const payload = await api("/users/me/profile/import", { method: "POST", formData });
    const result = payload.data;

    $("#profile-form").elements.text.value = result.text;

    const box = $("#profile-status");
    box.className = "msg ok";
    box.textContent = `已从「${result.filename}」解析出 ${result.chars} 字。请核对下面的文本，确认无误后点「保存」。`;
    box.hidden = false;
  } catch (err) {
    showProfileError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function saveProfile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const text = form.elements.text.value.trim();

  $("#profile-msg").hidden = true;
  if (!text) {
    showProfileError("简历内容不能为空");
    return;
  }

  const btn = $("#btn-profile-save");
  btn.disabled = true;
  btn.textContent = "保存中…";

  try {
    const payload = await api("/users/me/profile", { method: "PUT", body: { text } });
    updateProfileStatus(payload.data);
    $("#dlg-profile").close();
    toast(`简历已保存（${payload.data.chars} 字）`);
  } catch (err) {
    showProfileError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "保存";
  }
}

async function clearProfile() {
  const ok = window.confirm("清空简历？清空后「AI 分析」会被拒绝，直到你重新上传。");
  if (!ok) return;

  try {
    const payload = await api("/users/me/profile", { method: "DELETE" });
    $("#profile-form").elements.text.value = "";
    updateProfileStatus(payload.data);
    toast("简历已清空");
  } catch (err) {
    showProfileError(err.message);
  }
}


/* ---------- 助手（独立视图，不是弹窗） ---------- */
let assistantBusy = false;

function showAssistantView() {
  hideBoot();
  $("#view-login").hidden = true;
  $("#view-app").hidden = true;
  $("#view-assistant").hidden = false;
}

function closeAssistantView() {
  $("#view-assistant").hidden = true;
  $("#view-app").hidden = false;
}

/* 一条消息 = 头像 + 气泡 */
function messageRow(role, content) {
  const row = el("div", `msg-row ${role}`);
  const avatar = el("div", `avatar ${role === "user" ? "me" : "ai"}`,
    role === "user" ? "我" : "AI");
  const bubble = el("div", `bubble ${role}`, content);
  row.append(avatar, bubble);
  return row;
}

/* 连续的 tool 消息合并成一个可折叠块：
 * 一次回答里可能搜 2~3 次，如果每条都展开会把屏幕占满，
 * 而大多数时候用户只关心结论，不关心搜了哪几个词。 */
function toolBlock(tools) {
  const box = el("details", "tool-block");
  box.append(el("summary", null, `🔍 搜索了 ${tools.length} 次（点开看查了什么）`));

  const items = el("div", "tool-items");
  for (const tool of tools) {
    items.append(el("div", "tool-item", tool.content));
  }
  box.append(items);
  return box;
}

function renderAssistantMessages(messages) {
  const log = $("#assistant-log");
  log.replaceChildren();

  if (messages.length === 0) {
    log.append(el("p", "empty",
      "问我什么都行：岗位库里先准备哪个、某家公司做什么、简历该补什么。"));
    return;
  }

  let pendingTools = [];
  const flushTools = () => {
    if (pendingTools.length) {
      log.append(toolBlock(pendingTools));
      pendingTools = [];
    }
  };

  for (const message of messages) {
    if (message.role === "tool") {
      pendingTools.push(message);
      continue;
    }
    flushTools();
    log.append(messageRow(message.role, message.content));
  }
  flushTools();

  log.scrollTop = log.scrollHeight;
}

async function openAssistant() {
  showAssistantView();
  const log = $("#assistant-log");
  log.replaceChildren(el("p", "empty", "加载中…"));

  try {
    const payload = await api("/assistant/messages");
    renderAssistantMessages(payload.data);
  } catch (err) {
    log.replaceChildren(el("p", "empty", err.message));
  }
}

async function sendAssistant(text) {
  const content = String(text || "").trim();
  if (!content || assistantBusy) return;

  const log = $("#assistant-log");
  const form = $("#assistant-form");
  const sendBtn = $("#btn-assistant-send");

  assistantBusy = true;
  sendBtn.disabled = true;
  sendBtn.textContent = "…";
  form.elements.content.disabled = true;
  form.elements.content.value = "";

  log.append(messageRow("user", content));
  const pending = el("div", "bubble assistant", "正在想…");
  const pendingRow = el("div", "msg-row assistant");
  pendingRow.append(el("div", "avatar ai", "AI"), pending);
  log.append(pendingRow);
  log.scrollTop = log.scrollHeight;

  try {
    await api("/assistant/messages", { method: "POST", body: { content } });
    // 后端会插入 tool 消息（搜索记录），重新拉一次历史最准确
    const history = await api("/assistant/messages");
    renderAssistantMessages(history.data);
  } catch (err) {
    pending.className = "bubble tool";
    pending.textContent = err.message;
  } finally {
    assistantBusy = false;
    sendBtn.disabled = false;
    sendBtn.textContent = "发送";
    form.elements.content.disabled = false;
    form.elements.content.focus();
  }
}

async function clearAssistant() {
  const ok = window.confirm("清空对话记录？岗位库和简历不受影响。");
  if (!ok) return;

  try {
    await api("/assistant/messages", { method: "DELETE" });
    renderAssistantMessages([]);
    toast("对话已清空");
  } catch (err) {
    toast(err.message, true);
  }
}

/* ---------- 表单 ---------- */
/* job  = 从列表点「编辑」时传入（有 id，会走 PATCH）
 * draft = 从截图识别出来的草稿（无 id，走 POST，且要提示用户核对） */
function openForm(job, draft = null) {
  state.editId = job ? job.id : null;
  $("#dlg-title").textContent = job ? "编辑投递" : (draft ? "确认识别结果" : "新增投递");
  $("#form-msg").hidden = true;

  const form = $("#job-form");
  form.reset();

  const source = job || draft;
  if (source) {
    for (const key of ["company", "position", "status", "source", "source_detail",
      "salary_min", "salary_max", "salary_note", "url", "apply_url", "published_at",
      "company_business", "description", "note"]) {
      const input = form.elements[key];
      if (input) input.value = source[key] ?? "";
    }
    if (form.elements.next_interview_at) {
      form.elements.next_interview_at.value = toLocalInput(source.next_interview_at);
    }
  }

  const hint = $("#draft-hint");
  if (draft) {
    const percent = Math.round((draft.confidence ?? 0) * 100);
    hint.textContent = `已从截图识别（信心 ${percent}%）。请核对后再保存——识别错的地方直接改。`;
    hint.hidden = false;
  } else {
    hint.hidden = true;
  }

  $("#dlg-job").showModal();
  if (draft) {
    // 识别结果里公司/岗位可能缺失，把焦点放到第一个空的关键字段上
    const firstEmpty = !draft.company ? form.elements.company
      : (!draft.position ? form.elements.position : null);
    if (firstEmpty) firstEmpty.focus();
  }
}

function toLocalInput(value) {
  if (!value) return "";
  return String(value).replace(" ", "T").slice(0, 16);
}

function closeForm() {
  state.editId = null;
  $("#draft-hint").hidden = true;
  $("#dlg-job").close();
}

async function submitForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const msg = $("#form-msg");
  const btn = $("#btn-save");

  const payload = {
    company: form.elements.company.value.trim(),
    position: form.elements.position.value.trim(),
    status: form.elements.status.value,
    source: form.elements.source.value,
    source_detail: emptyToNull(form.elements.source_detail.value),
    salary_min: emptyToNull(form.elements.salary_min.value, true),
    salary_max: emptyToNull(form.elements.salary_max.value, true),
    salary_note: emptyToNull(form.elements.salary_note.value),
    url: emptyToNull(form.elements.url.value),
    apply_url: emptyToNull(form.elements.apply_url.value),
    published_at: emptyToNull(form.elements.published_at.value),
    company_business: emptyToNull(form.elements.company_business.value),
    description: emptyToNull(form.elements.description.value),
    note: emptyToNull(form.elements.note.value),
    next_interview_at: emptyToNull(form.elements.next_interview_at.value),
  };

  msg.hidden = true;
  btn.disabled = true;
  btn.textContent = "保存中…";

  try {
    if (state.editId) {
      await api(`/jobs/${state.editId}`, { method: "PATCH", body: payload });
      toast("已更新");
    } else {
      await api("/jobs", { method: "POST", body: payload });
      toast("已新增");
    }
    closeForm();
    await refresh();
  } catch (err) {
    msg.textContent = err.message;
    msg.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "保存";
  }
}

function emptyToNull(value, asNumber = false) {
  const text = String(value ?? "").trim();
  if (text === "") return null;
  return asNumber ? Number(text) : text;
}

/* ---------- 删除 ---------- */
async function removeJob(job) {
  const ok = window.confirm(`删除「${job.company} · ${job.position}」？删除后不可恢复。`);
  if (!ok) return;

  try {
    await api(`/jobs/${job.id}`, { method: "DELETE" });
    toast("已删除");
    await refresh();
  } catch (err) {
    toast(err.message, true);
  }
}

/* ---------- 启动 ---------- */
async function boot() {
  // 第一行就打印版本，方便一眼确认浏览器加载的是不是最新前端
  console.info(
    `[投递记录] 前端版本 ${APP_VERSION} | 简历功能: ${typeof openProfile === "function" ? "已加载" : "缺失（缓存旧版）"}`
  );

  $("#login-form").addEventListener("submit", doLogin);
  $("#register-form").addEventListener("submit", doRegister);
  $("#btn-toggle-mode").addEventListener("click", () => {
    const toRegister = $("#login-form").hidden === false;
    setAuthMode(toRegister ? "register" : "login");
    const form = toRegister ? $("#register-form") : $("#login-form");
    const first = form.querySelector("input");
    if (first) first.focus();
  });
  $("#btn-logout").addEventListener("click", () => logout());

  /* 我的简历 */
  $("#btn-profile").addEventListener("click", openProfile);
  $("#btn-profile-upload").addEventListener("click", () => $("#file-profile").click());
  $("#file-profile").addEventListener("change", (event) => {
    const input = event.currentTarget;
    const file = input.files && input.files[0];
    input.value = ""; // 清空，允许再选同一个文件
    importProfileFile(file);
  });
  $("#profile-form").addEventListener("submit", saveProfile);
  $("#btn-profile-cancel").addEventListener("click", () => $("#dlg-profile").close());
  $("#btn-profile-clear").addEventListener("click", clearProfile);

  /* 助手（全局唯一） */
  $("#btn-assistant").addEventListener("click", openAssistant);
  $("#btn-assistant-back").addEventListener("click", closeAssistantView);
  $("#btn-assistant-clear").addEventListener("click", clearAssistant);
  $("#assistant-form").addEventListener("submit", (event) => {
    event.preventDefault();
    sendAssistant(event.currentTarget.elements.content.value);
  });
  $("#assistant-quick").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-q]");
    if (button) sendAssistant(button.dataset.q);
  });

  $("#btn-new").addEventListener("click", () => openForm(null));
  $("#btn-refresh").addEventListener("click", refresh);

  /* 截图导入：按钮选文件 + 全局粘贴（Ctrl+V）两条入口 */
  $("#btn-shot").addEventListener("click", () => $("#file-shot").click());
  $("#file-shot").addEventListener("change", (event) => {
    const input = event.currentTarget;
    const file = input.files && input.files[0];
    input.value = ""; // 清空，允许再选同一张图
    importScreenshot(file);
  });

  document.addEventListener("paste", (event) => {
    if ($("#view-app").hidden) return;

    const items = event.clipboardData ? event.clipboardData.items : [];
    const imageItem = Array.from(items).find(
      (item) => item.kind === "file" && item.type.startsWith("image/")
    );

    // 只有"剪贴板里确实是图片"时才拦截。
    // 纯文字粘贴必须放行，否则会破坏用户在输入框里的正常粘贴；
    // 反过来，图片不应该因为焦点在输入框就被忽略——那样用户会以为功能坏了。
    if (!imageItem) return;

    const file = imageItem.getAsFile();
    if (!file) return;

    event.preventDefault();
    importScreenshot(file);
  });
  $("#btn-cancel").addEventListener("click", closeForm);
  $("#job-form").addEventListener("submit", submitForm);

  /* 状态筛选：走服务端，所以要重新拉数据（不能只 render） */
  $("#filter-status").addEventListener("change", (event) => {
    state.statusFilter = event.currentTarget.value;
    refresh(true);
  });

  /* 搜索框：防抖 300ms，避免每个字符都打一次接口 */
  let queryTimer = null;
  $("#q-input").addEventListener("input", (event) => {
    const value = event.currentTarget.value.trim();
    clearTimeout(queryTimer);
    queryTimer = setTimeout(() => {
      if (value === state.query) return;
      state.query = value;
      refresh(true);
    }, 300);
  });

  /* 分组方式：纯展示层，不需要请求后端 */
  $("#group-by").addEventListener("change", (event) => {
    state.groupBy = event.currentTarget.value;
    state.activeGroup = "all";   // 换维度后回到「全部」，否则旧 key 在新维度里不存在
    render();
  });

  /* 分组 Tab：事件委托，Tab 是动态生成的 */
  $("#tab-bar").addEventListener("click", (event) => {
    const tab = event.target.closest("button.tab");
    if (!tab) return;
    state.activeGroup = tab.dataset.key;
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  $("#btn-clear-filter").addEventListener("click", () => {
    state.statusFilter = "";
    state.query = "";
    $("#filter-status").value = "";
    $("#q-input").value = "";
    refresh(true);
  });

  if (!state.token) {
    showLogin();
    return;
  }

  // 有 token：先验证是否还有效，避免闪一下主界面又弹回登录
  try {
    const payload = await api("/users/me");
    state.user = payload.data;
    localStorage.setItem(USER_KEY, JSON.stringify(payload.data));
    showApp();
    await refresh();
  } catch (err) {
    if (err && err.status === 401) {
      // token 真的失效（过期，或被别处登录顶掉）——api() 内部已清 token
      logout(false);
      toast(err.message || "登录已失效，请重新登录", true);
    } else {
      // 网络错误 / 服务 503：**绝不能清 token**。
      // 否则容器重启、断网、Wi-Fi 切换都会把用户永久登出，被迫重新输密码。
      // 保留 token，用户刷新一次就能自动恢复。
      showLogin();
      toast("连接服务器失败，请稍后刷新重试", true);
    }
  }
}

document.addEventListener("DOMContentLoaded", boot);
