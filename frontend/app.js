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
  detailId: null,
  detailJob: null,
  answers: new Map(),
  prepFilter: 'all',
  grading: new Set(),
  roundView: new Map(),
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

/* 顶部小提示：3 秒自动消失，不打断输入、不移动视口。
 * 用于"已评估/追问已就绪"这类异步结果——用户可能已经在做下一题了。 */
let topToastTimer = null;
function showTopToast(message) {
  const box = $("#top-toast");
  if (!box) return;
  box.textContent = message;
  box.hidden = false;
  // 强制回流，让重复调用时过渡动画能重放
  void box.offsetWidth;
  box.classList.add("show");
  clearTimeout(topToastTimer);
  topToastTimer = setTimeout(() => {
    box.classList.remove("show");
    setTimeout(() => { box.hidden = true; }, 220);
  }, 3000);
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

/* 统一视图切换：login / app / assistant / detail 四选一。
 * 之前各函数手动把别的视图 hide 掉，加到第四个视图时容易漏，收敛成一个入口。 */
function setView(name) {
  hideBoot();
  $("#view-login").hidden = name !== "login";
  $("#view-app").hidden = name !== "app";
  $("#view-assistant").hidden = name !== "assistant";
  $("#view-detail").hidden = name !== "detail";
}

function showApp() {
  setView("app");
  $("#whoami").textContent = state.user ? state.user.name : "";
}

function showLogin() {
  setView("login");
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
  state.detailId = null;
  state.detailJob = null;
  state.answers = new Map();
  state.prepFilter = "all";
  state.grading.clear();
  state.roundView = new Map();
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

  const btnDetail = el("button", "primary small", "详情");
  btnDetail.addEventListener("click", () => openDetail(job.id));
  actions.append(btnDetail);

  const btnEdit = el("button", "ghost small", "编辑");
  btnEdit.addEventListener("click", () => openForm(job));

  const btnDelete = el("button", "ghost small", "删除");
  btnDelete.addEventListener("click", () => removeJob(job));

  actions.append(btnEdit, btnDelete);
  card.append(actions);

  // 分析详情不再折叠在卡片里（那会让一张卡片占满整屏），
  // 改到「详情」页展示完整内容；卡片只留分数和档位用于扫读。
  return card;
}

function parseStoredJson(raw) {
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


/* ---------- 岗位详情（独立视图） ---------- */
/* 列表负责扫读，详情负责看内容：JD 原文、备注、分析全文都在这里。
 * 列表接口不返回 JD 全文（JobOut 有意排除），所以进来要单独拉一次详情。 */
async function openDetail(jobId) {
  state.detailId = jobId;
  setView("detail");

  const body = $("#detail-body");
  body.replaceChildren(el("p", "empty", "加载中…"));

  try {
    // 详情和练习记录一起拿：练习状态决定每道题渲染成什么样子
    const [detail, answers] = await Promise.all([
      api(`/jobs/${jobId}`),
      api(`/jobs/${jobId}/answers`),
    ]);
    state.detailJob = detail.data;
    state.answers = new Map(answers.data.map((item) => [item.question_hash, item]));
    renderDetail(detail.data);
  } catch (err) {
    body.replaceChildren(el("p", "empty", err.message));
  }
}

function closeDetail() {
  state.detailId = null;
  state.detailJob = null;
  state.answers = new Map();
  state.prepFilter = "all";
  state.grading.clear();
  setView("app");
}

function detailSection(title, contentNode) {
  const section = el("section", "detail-section");
  section.append(el("h2", null, title));
  section.append(contentNode);
  return section;
}

function renderDetail(job) {
  const body = $("#detail-body");
  body.replaceChildren();

  /* 标题行：公司 + 岗位 + 状态 */
  const titleRow = el("div", "detail-title-row");
  const title = el("div");
  title.append(el("h1", null, job.company));
  title.append(el("div", "detail-position", job.position));
  titleRow.append(title);
  titleRow.append(el("span", `badge ${STATUS_CLASS[job.status] || "st-pending"}`, job.status));
  body.append(titleRow);

  /* 事实清单 */
  const facts = el("dl", "detail-facts");
  const addFact = (label, value) => {
    if (value === null || value === undefined || value === "") return;
    const item = el("div");
    item.append(el("dt", null, label));
    item.append(el("dd", null, String(value)));
    facts.append(item);
  };

  if (job.salary_min != null || job.salary_max != null) {
    const note = job.salary_note ? `·${job.salary_note}` : "";
    addFact("薪资", `${job.salary_min ?? "?"}-${job.salary_max ?? "?"}k${note}`);
  }
  addFact("渠道", job.source_detail ? `${job.source}·${job.source_detail}` : job.source);
  addFact("发布", job.published_at);
  addFact("下次面试", job.next_interview_at ? formatDateTime(job.next_interview_at) : null);
  addFact("公司业务", job.company_business);
  addFact("录入", formatDateTime(job.created_at));
  if (facts.childNodes.length) body.append(facts);

  /* 两类链接 */
  const links = el("div", "detail-links");
  if (job.apply_url) {
    const apply = el("a", "link-apply", "去投递 ↗");
    apply.href = job.apply_url;
    apply.target = "_blank";
    apply.rel = "noopener noreferrer";
    links.append(apply);
  }
  if (job.url) {
    const jd = el("a", "link-jd", "岗位详情页 ↗");
    jd.href = job.url;
    jd.target = "_blank";
    jd.rel = "noopener noreferrer";
    links.append(jd);
  }
  if (links.childNodes.length) body.append(links);

  /* AI 结论 */
  if (job.match_score != null) {
    const scoreRow = el("div", "detail-score");
    scoreRow.append(el("span", "badge score", `${job.match_score} 分`));
    if (job.verdict) {
      scoreRow.append(el("span", `badge ${VERDICT_CLASS[job.verdict] || "vd-apply"}`, job.verdict));
    }
    if (job.analyzed_at) {
      scoreRow.append(el("span", "muted", `分析于 ${formatDateTime(job.analyzed_at)}`));
    }
    body.append(scoreRow);
  }

  /* JD 原文 —— 这是用户最想看的东西，放在正文第一块 */
  body.append(detailSection(
    "JD 原文",
    job.description
      ? el("p", "detail-pre", job.description)
      : el("p", "empty", "这条记录没有 JD 原文，可以在「编辑」里补上")
  ));

  /* 备注 */
  if (job.note) body.append(detailSection("备注", el("p", "detail-pre", job.note)));

  /* AI 分析全文 */
  const analysis = parseStoredJson(job.analysis);
  if (analysis) {
    const wrap = el("div", "analysis");
    wrap.append(...renderAnalysisParts(analysis));
    body.append(detailSection("AI 分析", wrap));
  }

  /* 面试准备 */
  body.append(detailSection("面试准备", renderInterviewPrep(job)));

  const spacer = el("div", "detail-spacer");
  body.append(spacer);

  /* 回到详情页时，如果上次有没保存的改动，主动提醒一次 */
  remindUnsavedDrafts();
}

/* ---------- 面试准备（详情页里的一块） ---------- */
const LAYER_NAME = { 0: "原题", 1: "第 1 层 · 事实", 2: "第 2 层 · 决策", 3: "第 3 层 · 边界" };

const BASIS_LABEL = { resume: "来自简历", jd: "来自 JD", general: "通用知识" };
const STATUS_LABEL = { ok: "能答", gap: "答不上来", unknown: "不确定" };
// gap 排最前：面试前时间有限，先攻最可能翻车的
const STATUS_ORDER = { gap: 0, unknown: 1, ok: 2 };

// 练习状态 → 展示
const PRACTICE_LABEL = {
  untried: "没练过",
  tried: "练过",
  partial: "部分掌握",
  mastered: "已掌握",
  wrong: "不会",
};
const PRACTICE_ORDER = { wrong: 0, tried: 1, partial: 2, untried: 3, mastered: 4 };

/* 题目文本指纹（FNV-1a 32 位）。
 * **必须和后端 services/interview.py 的 question_hash 完全一致**，
 * 否则查不到作答记录。用 FNV-1a 而不是 sha256，
 * 是因为 JS 里同步算 sha256 要用 SubtleCrypto（异步），很别扭。 */
function questionHash(text) {
  let hash = 0x811C9DC5;
  for (const byte of new TextEncoder().encode(text)) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

function renderInterviewPrep(job) {
  const wrap = el("div", "prep");

  const prep = parseStoredJson(job.interview_prep);
  if (!prep || !Array.isArray(prep.questions) || prep.questions.length === 0) {
    wrap.append(el("p", "hint",
      "按这份 JD 和你的简历，预测这场面试会问什么，并标出你现在答不上来的。"));
    const btn = el("button", "primary small", "生成面试题（约 20-30 秒）");
    btn.addEventListener("click", () => generatePrep(job.id, btn, false));
    wrap.append(btn);
    return wrap;
  }

  /* 头部：统计 + 重新生成 */
  const head = el("div", "prep-head");
  const records = [...state.answers.values()];
  const practiced = records.filter((r) => r.status !== "untried").length;
  head.append(el("span", "muted",
    `${prep.questions.length} 道题 · 已练 ${practiced} 道 · 生成于 ${formatDateTime(job.interview_prep_at)}`));
  const again = el("button", "ghost small", "重新生成");
  again.addEventListener("click", () => generatePrep(job.id, again, true));
  head.append(again);
  wrap.append(head);

  /* 没拆关键点就不能练，先给按钮 */
  const missingPoints = prep.questions.filter((q) => !q.key_points || !q.key_points.length);
  if (missingPoints.length) {
    const tip = el("div", "prep-needpoints");
    tip.append(el("span", "muted",
      `还有 ${missingPoints.length} 道题没拆解关键点，拆完才能练（约 5 秒，不用重新生成整套）`));
    const btn = el("button", "primary small", "拆解关键点");
    btn.addEventListener("click", () => fillKeyPoints(job.id, btn));
    tip.append(btn);
    wrap.append(tip);
  }

  /* 要补的点 */
  if (Array.isArray(prep.gaps_summary) && prep.gaps_summary.length) {
    wrap.append(el("h3", "prep-sub", "面试前先补这些"));
    const list = el("ol", "prep-gaps");
    for (const gap of prep.gaps_summary) list.append(el("li", null, gap));
    wrap.append(list);
  }

  /* 准备建议 */
  if (prep.prep_advice) {
    wrap.append(el("h3", "prep-sub", "怎么用这份准备"));
    wrap.append(el("p", "prep-advice", prep.prep_advice));
  }

  /* 筛选：全部 / 待练 / 错题 */
  const filterRow = el("div", "prep-filter");
  for (const [key, label] of [["all", "全部"], ["todo", "待练"], ["wrong", "错题本"]]) {
    const chip = el("button", `tab${state.prepFilter === key ? " active" : ""}`, label);
    chip.type = "button";
    chip.addEventListener("click", () => {
      state.prepFilter = key;
      renderDetail(state.detailJob);   // 只重渲染，不重新请求
    });
    filterRow.append(chip);
  }
  wrap.append(filterRow);

  /* 题目：错题 → 练过 → 部分 → 没练 → 已掌握 */
  const questions = [...prep.questions].sort((a, b) => {
    const ra = state.answers.get(questionHash(a.question));
    const rb = state.answers.get(questionHash(b.question));
    const oa = PRACTICE_ORDER[ra?.status || "untried"] ?? 9;
    const ob = PRACTICE_ORDER[rb?.status || "untried"] ?? 9;
    if (oa !== ob) return oa - ob;
    return (STATUS_ORDER[a.your_status] ?? 9) - (STATUS_ORDER[b.your_status] ?? 9);
  });

  let shown = 0;
  for (const question of questions) {
    const record = state.answers.get(questionHash(question.question));
    const status = record?.status || "untried";

    if (state.prepFilter === "todo" && status === "mastered") continue;
    if (state.prepFilter === "wrong" && status !== "wrong") continue;

    wrap.append(questionCard(question, record));
    shown += 1;
  }

  if (shown === 0) {
    wrap.append(el("p", "empty",
      state.prepFilter === "wrong" ? "还没有错题，练过的题里没有标「我不会」的" : "没有符合筛选的题"));
  }

  return wrap;
}

function questionCard(question, record) {
  const status = record?.status || "untried";
  const hash = questionHash(question.question);
  const card = el("div", `q-card q-${question.your_status}`);
  if (state.grading.has(hash)) card.classList.add("grading");
  card.dataset.hash = hash;

  const head = el("div", "q-head");
  head.append(el("span", `q-status q-status-${question.your_status}`,
    STATUS_LABEL[question.your_status] || "不确定"));
  head.append(el("span", `q-basis q-basis-${question.basis}`,
    BASIS_LABEL[question.basis] || question.basis));
  head.append(el("span", `q-practice q-practice-${status}`,
    PRACTICE_LABEL[status] || status));
  // 有未保存的草稿 → 卡片上直接标出来
  if (hasDraft(hash)) head.append(el("span", "draft-badge", "未保存"));
  card.append(head);

  card.append(el("p", "q-text", question.question));

  /* 依据 / 为什么问 默认折叠。
     这两条是"关于题目的元信息"，依据常常是一整段简历或 JD 原句，
     展开能占掉半屏；而用户真正要看的是题目本身和关键点。 */
  if (question.basis_quote || question.why_asked) {
    const meta = el("details", "q-meta");
    meta.append(el("summary", null,
      `依据 · ${BASIS_LABEL[question.basis] || question.basis}`));
    if (question.basis_quote) {
      meta.append(el("p", "q-quote", question.basis_quote));
    }
    if (question.why_asked) {
      meta.append(el("p", "q-why", `为什么问：${question.why_asked}`));
    }
    card.append(meta);
  }

  /* 关键点：默认折叠，但**摘要上带数字**。
     不折叠的两个问题：
       1. 5 条要点在手机上就是 12~15 行，比"依据"还占地方；
       2. 更严重——它列在输入框上方，答题前就把答案要点给看了，
          那就不是 recall 练习，而是看着答案抄。
     摘要写"覆盖 2/5 · 说错 1"，一眼知道练得怎么样，明细点开再看。 */
  if (question.key_points?.length) {
    const pointsBox = el("details", "q-points-box");
    pointsBox.append(el("summary", null, keyPointsSummary(question, record)));
    pointsBox.append(renderKeyPoints(question.key_points, record));
    card.append(pointsBox);
  }

  /* 参考答案默认收起：面试前想先自测 */
  const answer = el("details", "q-answer");
  answer.append(el("summary", null, "看参考答案"));
  answer.append(el("p", "q-answer-text", question.reference_answer));
  card.append(answer);

  if (question.follow_up) {
    card.append(el("p", "q-followup", `可能的追问：${question.follow_up}`));
  }

  card.append(practiceBlock(question, record));
  return card;
}

/* 关键点折叠块的摘要：没练过只说条数，练过就报覆盖数字 */
function keyPointsSummary(question, record) {
  const total = question.key_points.length;
  if (!record || record.status === "untried") {
    return `关键点（${total} 条）`;
  }
  const covered = (record.covered || []).length;
  const wrong = (record.wrong || []).length;
  return wrong
    ? `关键点 · 覆盖 ${covered}/${total} · 说错 ${wrong}`
    : `关键点 · 覆盖 ${covered}/${total}`;
}

function renderKeyPoints(points, record) {
  const covered = new Set(record?.covered || []);
  const wrongMap = new Map((record?.wrong || []).map((w) => [w.index, w.why]));

  const box = el("ul", "q-points");
  points.forEach((point, index) => {
    let mark = " ";
    let cls = "q-point";
    if (covered.has(index)) { mark = "✓"; cls += " ok"; }
    else if (wrongMap.has(index)) { mark = "✗"; cls += " wrong"; }
    else if (record && record.status !== "untried") { mark = "·"; cls += " missing"; }

    const item = el("li", cls);
    item.append(el("span", "q-point-mark", mark));
    item.append(el("span", null, point));
    if (wrongMap.has(index)) {
      item.append(el("span", "q-point-why", wrongMap.get(index)));
    }
    box.append(item);
  });
  return box;
}

/* 只替换这一张卡片，并做滚动锚定。
 *
 * 为什么不能整页重渲染：用户可能正在往下做第二道题，
 * 整页重渲染会把他滚回顶部，输入到一半的内容也会丢。
 * 锚定做法：记录替换前卡片顶部的屏幕位置，替换后把滚动补偿回来，
 * 这样"卡片在自己变高"，但用户的视口纹丝不动。 */
function patchCard(card, question, record) {
  /* 锚点选择：优先跟着用户正在输入的那个文本框。
     理由——被评估的卡片会变高（多出结论和追问），它下面的一切都会下移。
     如果用户此刻正在另一道题里打字，那段文字会从眼前跑掉；
     而如果用户没在打字，让内容下移是可以接受的。
     所以有焦点时钉住焦点，没焦点时才钉住被替换的卡片。 */
  const active = document.activeElement;
  const anchor =
    active && active.tagName === "TEXTAREA" && !card.contains(active) ? active : card;

  const beforeTop = anchor.getBoundingClientRect().top;
  const next = questionCard(question, record);
  card.replaceWith(next);
  const afterTop = anchor.getBoundingClientRect().top;

  // 补偿滚动，让锚点在视口里的位置保持不变
  if (afterTop !== beforeTop) window.scrollBy(0, afterTop - beforeTop);
  return next;
}

/* ---------- 草稿保护（未保存的修改不丢） ---------- */
/* 每个 (岗位, 题目, 轮次) 一个 key，存在 localStorage。
   手机上切后台/杀进程都不会丢，回到页面时提醒。 */
function draftKey(hash, round) {
  return `draft:${state.detailId}:${hash}:${round}`;
}

function readDraft(hash, round) {
  try {
    return localStorage.getItem(draftKey(hash, round));
  } catch {
    return null;
  }
}

function writeDraft(hash, round, value) {
  try {
    localStorage.setItem(draftKey(hash, round), value);
  } catch {
    /* 隐私模式 / 配额满：降级，不阻塞操作 */
  }
}

function clearDraft(hash, round) {
  try {
    localStorage.removeItem(draftKey(hash, round));
  } catch {
    /* 同上 */
  }
}

function hasDraft(hash) {
  return [0, 1, 2, 3].some((round) => readDraft(hash, round) !== null);
}

function pendingDrafts() {
  const found = [];
  const prefix = `draft:${state.detailId}:`;
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key && key.startsWith(prefix)) {
        const parts = key.split(":");
        found.push({ hash: parts[2], round: Number(parts[3]) });
      }
    }
  } catch {
    /* 忽略 */
  }
  return found;
}

function remindUnsavedDrafts() {
  const drafts = pendingDrafts();
  if (!drafts.length) return;
  showTopToast(`有 ${drafts.length} 处修改未保存，点对应题目的「保存」`);
}

/* 手机切后台再回来：把没保存的改动提醒出来。
   草稿是每次输入就写进 localStorage 的，所以切后台/退出都不会丢。 */
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && state.detailId) {
    remindUnsavedDrafts();
  }
});

/* ---------- 练习区：轮次导航 + 编辑 + 提交 ---------- */
/* 设计要点（和用户讨论后定的）：
   1. 上一轮的问答**不消失**：所有轮次都留在 transcript 里，
      用「← / →」翻回去看当时的回答**和当时的评估**。
   2. 历史轮次可以改文字，但**不重新评估**：第 2 层追问是基于第 1 层的
      答案问出来的，重算会连锁改动后面所有轮；想真的重练走「重新练一遍」。
   3. 改历史轮次要手动点保存，失焦时给硬弹窗确认——手机误触太多。
   4. 没保存的改动写进 localStorage，退出也不丢，回来时提醒。
*/
function practiceBlock(question, record) {
  const box = el("div", "practice");
  const hash = questionHash(question.question);
  const rounds = record?.transcript || [];
  const grading = state.grading.has(hash);

  if (!question.key_points?.length) {
    box.append(el("p", "hint", "这道题还没拆出关键点，点上面的「拆解关键点」"));
    return box;
  }

  /* 从没练过 → 直接给输入框（第 0 轮就是原题） */
  if (!rounds.length) {
    box.append(answerForm(question, hash, null, null, grading, 0, false));
    return box;
  }

  const pendingIndex = rounds.findIndex((item) => !item.answer);
  const lastIndex = rounds.length - 1;

  let viewIndex = state.roundView.get(hash);
  if (viewIndex === undefined || viewIndex > lastIndex) {
    // 有未答的追问就停在它上面，否则停在最后一轮
    viewIndex = pendingIndex >= 0 ? pendingIndex : lastIndex;
    state.roundView.set(hash, viewIndex);
  }

  const round = rounds[viewIndex];
  const isPending = !round.answer;

  /* 多于一轮才显示导航 */
  if (rounds.length > 1) {
    const nav = el("div", "round-nav");

    const prev = el("button", "ghost small", "←");
    prev.type = "button";
    prev.disabled = viewIndex === 0;
    prev.addEventListener("click", () => {
      state.roundView.set(hash, viewIndex - 1);
      refreshPracticeCard(question, hash);
    });

    const label = el("span", "round-label",
      `${LAYER_NAME[round.layer] || "追问"}（${viewIndex + 1}/${rounds.length}）`);

    const next = el("button", "ghost small", "→");
    next.type = "button";
    next.disabled = viewIndex === lastIndex;
    next.addEventListener("click", () => {
      state.roundView.set(hash, viewIndex + 1);
      refreshPracticeCard(question, hash);
    });

    nav.append(prev, label, next);
    box.append(nav);
  }

  /* 这一轮问了什么 */
  if (isPending) {
    const ask = el("div", "practice-ask");
    ask.append(el("span", "practice-ask-layer", LAYER_NAME[round.layer] || "追问"));
    ask.append(el("p", "practice-ask-text", round.question));
    box.append(ask);
  } else {
    box.append(el("p", "practice-q", `问：${round.question}`));

    const answerBox = el("div", "practice-answer");
    answerBox.append(el("span", "practice-answer-label",
      round.edited ? "我的回答（已修改）" : "我的回答"));
    answerBox.append(el("p", "practice-a", round.answer));
    box.append(answerBox);

    /* 那一轮的评估快照：翻回去看到的是"当时的结论"，不是最新一次 */
    const evaluation = round.evaluation;
    if (evaluation) {
      const total = question.key_points.length;
      box.append(el("p", "practice-verdict",
        `当时评估：覆盖 ${(evaluation.covered || []).length}/${total}` +
        ` · 说错 ${(evaluation.wrong || []).length}` +
        ` · 漏掉 ${(evaluation.missing || []).length}`));
      if (evaluation.verdict) {
        box.append(el("p", "practice-verdict", evaluation.verdict));
      }
    }

    box.append(answerForm(question, hash, round, viewIndex, grading, 0, false));

    /* 已收口且停在最后一轮 → 给"从头再来"的入口。
       改历史答案是"只存不重算"，真想重练必须走这里。 */
    if (record?.finish_reason && viewIndex === lastIndex) {
      const again = el("button", "ghost small", "重新练一遍");
      again.type = "button";
      again.addEventListener("click", async () => {
        const ok = window.confirm("重新练一遍？所有轮次的记录会被清空，题目和关键点保留。");
        if (!ok) return;
        try {
          await api(`/jobs/${state.detailId}/answers/${hash}`, {
            method: "PATCH",
            body: { reset: true },
          });
          [0, 1, 2, 3].forEach((item) => clearDraft(hash, item));
          state.roundView.delete(hash);
          await reloadAnswers();
          refreshPracticeCard(question, hash);
          showTopToast("已重置，可以重新练");
        } catch (err) {
          toast(err.message, true);
        }
      });
      box.append(again);
    }
  }

  /* 未答的追问：**输入框永远是空的**。
     这是本次修的 bug：以前用 record.answer 回填，
     新的追问配上一轮的答案，看起来莫名其妙。 */
  if (isPending) {
    const depth = record?.depth || 0;
    const finished = Boolean(record?.finish_reason);
    box.append(answerForm(question, hash, null, null, grading, depth, finished));
  }

  return box;
}

/* 输入/编辑表单。
 *   round === null → 回答"下一个问题"（新答案，提交即评估）
 *   round 有值     → 编辑历史某一轮（只存文字，不重算）
 */
function answerForm(question, hash, round, roundIndex, grading, depth, finished) {
  const form = el("form", "practice-form");
  const isEdit = round !== null;
  const draft = isEdit ? readDraft(hash, roundIndex) : null;
  const stored = isEdit ? (round.answer || "") : "";
  const dirtyFromDraft = draft !== null && draft !== stored;

  if (dirtyFromDraft) {
    form.append(el("p", "practice-warn", "有未保存的改动（上次离开时留下的）"));
  }

  const input = el("textarea", "practice-input");
  input.rows = 3;
  input.maxLength = 8000;
  // 新问题一定空着；编辑历史才回填（并优先用草稿）
  input.value = isEdit ? (dirtyFromDraft ? draft : stored) : "";
  input.placeholder = isEdit
    ? "修正这段回答（只改记录，不会重新评估）"
    : "先自己答一遍，别急着看参考答案";
  if (grading) input.disabled = true;
  form.append(input);

  const actions = el("div", "practice-actions");

  if (isEdit) {
    const save = el("button", "primary small", "保存");
    save.type = "button";
    save.addEventListener("click", async () => {
      const text = input.value.trim();
      if (!text) {
        showTopToast("内容不能为空");
        return;
      }
      if (text === stored) {
        clearDraft(hash, roundIndex);
        showTopToast("没有改动");
        return;
      }
      save.disabled = true;
      save.textContent = "保存中…";
      try {
        await api(`/jobs/${state.detailId}/answers/${hash}`, {
          method: "PATCH",
          body: { round: roundIndex, answer: text },
        });
        clearDraft(hash, roundIndex);
        await reloadAnswers();
        refreshPracticeCard(question, hash);
        showTopToast("已保存（不会重新评估）");
      } catch (err) {
        toast(err.message, true);
        save.disabled = false;
        save.textContent = "保存";
      }
    });
    actions.append(save);

    const cancel = el("button", "ghost small", "撤销改动");
    cancel.type = "button";
    cancel.addEventListener("click", () => {
      clearDraft(hash, roundIndex);
      input.value = stored;
      refreshPracticeCard(question, hash);
      showTopToast("已撤销改动");
    });
    actions.append(cancel);

    /* 失焦时硬弹窗：改过但没保存，不能默默丢掉 */
    input.addEventListener("blur", () => {
      const text = input.value.trim();
      if (text === stored) {
        clearDraft(hash, roundIndex);
        return;
      }
      writeDraft(hash, roundIndex, input.value);
      if (!text) return;
      if (window.confirm("这段修改还没保存，现在保存吗？")) {
        save.click();
      } else {
        showTopToast("改动已暂存，回来时会提醒");
      }
    });

    /* 每次输入就落草稿：退出页面/切后台都不会丢 */
    input.addEventListener("input", () => {
      const text = input.value;
      if (text.trim() === stored) clearDraft(hash, roundIndex);
      else writeDraft(hash, roundIndex, text);
    });
  } else {
    const label = grading
      ? "评估中…"
      : finished
        ? "重新练一遍"
        : depth === 0
          ? "提交并追问 1/3"
          : `提交并追问 ${depth + 1}/3`;

    const submit = el("button", "primary small", label);
    submit.type = "submit";
    submit.disabled = grading;
    actions.append(submit);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) {
        showTopToast("先写点东西再提交");
        return;
      }

      /* 只锁这一道题，别的题可以继续做 */
      state.grading.add(hash);
      submit.disabled = true;
      submit.textContent = "评估中…";
      input.disabled = true;
      const card = document.querySelector(`.q-card[data-hash="${hash}"]`);
      if (card) card.classList.add("grading");

      try {
        const result = await api(`/jobs/${state.detailId}/answers`, {
          method: "POST",
          body: { question_hash: hash, answer: text },
        });
        state.answers.set(hash, result.data);

        /* 关键顺序：先清"评估中"，再重渲染，否则新卡片仍是 disabled */
        state.grading.delete(hash);
        // 新追问出现 → 自动翻到最新那一轮
        state.roundView.set(hash, (result.data.transcript || []).length - 1);

        /* 只替换这一张卡片 + 滚动锚定：不整页重渲染，屏幕不跳 */
        const current = document.querySelector(`.q-card[data-hash="${hash}"]`);
        if (current) patchCard(current, question, result.data);

        const covered = result.data.covered.length;
        const total = result.data.total_points;
        showTopToast(
          result.data.next_question
            ? `已评估：覆盖 ${covered}/${total} · 新追问已就绪`
            : `已评估：覆盖 ${covered}/${total} · 本题已练完`
        );
      } catch (err) {
        state.grading.delete(hash);
        if (card) card.classList.remove("grading");
        toast(err.message, true);
        submit.disabled = false;
        submit.textContent = "重试";
        input.disabled = false;
      }
    });
  }

  form.append(actions);


  return form;
}

/* 重新拉一次作答记录（改了某一轮之后要同步） */
async function reloadAnswers() {
  if (!state.detailId) return;
  const answers = await api(`/jobs/${state.detailId}/answers`);
  state.answers = new Map(answers.data.map((item) => [item.question_hash, item]));
}

/* 只重渲染某张卡片里的练习区，不动整页（保持滚动位置） */
function refreshPracticeCard(question, hash) {
  const card = document.querySelector(`.q-card[data-hash="${hash}"]`);
  if (!card) return;
  const old = card.querySelector(".practice");
  if (!old) return;
  old.replaceWith(practiceBlock(question, state.answers.get(hash)));
}


async function markPractice(question, status) {
  // 「我不会」不调模型：模型必然判全部 missing，没必要花一次调用确认已知事实
  const hash = questionHash(question.question);
  const card = document.querySelector(`.q-card[data-hash="${hash}"]`);
  try {
    const result = await api(`/jobs/${state.detailId}/answers/${hash}`, {
      method: "PATCH",
      body: { status },
    });
    const record = { ...(state.answers.get(hash) || {}), ...result.data };
    state.answers.set(hash, record);
    if (card) patchCard(card, question, record);
    showTopToast(status === "wrong" ? "已加入错题本" : "已标记为掌握");
  } catch (err) {
    toast(err.message, true);
  }
}

async function fillKeyPoints(jobId, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "拆解中…";
  try {
    await api(`/jobs/${jobId}/interview-prep/key-points`, { method: "POST" });
    toast("关键点已补齐");
    await openDetail(jobId);
  } catch (err) {
    toast(err.message, true);
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function generatePrep(jobId, btn, force) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "生成中…（约 20 秒）";

  try {
    const path = `/jobs/${jobId}/interview-prep${force ? "?force=true" : ""}`;
    await api(path, { method: "POST" });
    toast("面试准备已生成");
    await openDetail(jobId);
  } catch (err) {
    toast(err.message, true);
    btn.disabled = false;
    btn.textContent = original;
  }
}

/* ---------- 助手（独立视图，不是弹窗） ---------- */
let assistantBusy = false;

function showAssistantView() {
  setView("assistant");
}

function closeAssistantView() {
  setView("app");
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
    await refresh(true);
    if (state.detailId) await openDetail(state.detailId); // 正在看详情就刷新它
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
    await refresh(true);
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
  /* 岗位详情 */
  $("#btn-detail-back").addEventListener("click", closeDetail);
  $("#btn-detail-edit").addEventListener("click", () => {
    if (state.detailJob) openForm(state.detailJob);
  });
  $("#btn-detail-delete").addEventListener("click", async () => {
    if (!state.detailJob) return;
    const job = state.detailJob;
    closeDetail();
    await removeJob(job);
  });

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
