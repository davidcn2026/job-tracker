/* 投递记录 · 前端逻辑
 *
 * 设计约束（详见交付说明）：
 *  1. 零依赖、零构建：原生 fetch + DOM API，浏览器直接跑
 *  2. 一律同源请求 /api/v1，不涉及 CORS
 *  3. 所有用户数据都用 textContent 写入，绝不拼接 innerHTML，避免 JD 原文里的脚本被执行
 *  4. 后端暂不支持筛选/分页参数，所以一次性取 100 条，在前端筛选和分页
 */

"use strict";

const API = "/api/v1";
const TOKEN_KEY = "jt_token";
const USER_KEY = "jt_user";
const PAGE_SIZE = 10;
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
  page: 1,
  editId: null,
  analyzing: new Set(),
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
  $("#view-login").hidden = true;
  $("#view-app").hidden = false;
  $("#whoami").textContent = state.user ? state.user.name : "";
}

function showLogin() {
  hideBoot();
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
  state.page = 1;
  state.items = [];
  state.analyzing.clear();
  state.editId = null;

  const select = $("#filter-status");
  if (select) select.value = "";

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

/* ---------- 数据加载 ---------- */
async function refresh() {
  const list = $("#list");
  list.replaceChildren();
  for (let i = 0; i < 3; i += 1) list.append(el("div", "skeleton"));

  try {
    const payload = await api(`/jobs?page=1&page_size=${FETCH_LIMIT}`);
    state.items = payload.data.list || [];
    state.page = 1;
    render();
  } catch (err) {
    list.replaceChildren();
    list.append(el("p", "empty", err.message));
  }
}

/* ---------- 渲染 ---------- */
function filtered() {
  if (!state.statusFilter) return state.items;
  return state.items.filter((job) => job.status === state.statusFilter);
}

function render() {
  const list = $("#list");
  const rows = filtered();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (state.page > pages) state.page = pages;

  const start = (state.page - 1) * PAGE_SIZE;
  const pageRows = rows.slice(start, start + PAGE_SIZE);

  list.replaceChildren();

  if (rows.length === 0) {
    list.append(el("p", "empty",
      state.statusFilter ? "这个状态下没有记录" : "还没有记录，点「+ 新增」开始"));
  } else {
    for (const job of pageRows) list.append(jobCard(job));
  }

  const pager = $("#pager");
  pager.hidden = rows.length <= PAGE_SIZE;
  $("#page-info").textContent = `第 ${state.page} / ${pages} 页 · 共 ${rows.length} 条`;
  $("#btn-prev").disabled = state.page <= 1;
  $("#btn-next").disabled = state.page >= pages;

  /* 筛选提示：只有真的在筛选时才出现，并给出"共几条、怎么取消" */
  const hint = $("#filter-hint");
  if (state.statusFilter) {
    hint.hidden = false;
    $("#filter-hint-text").textContent =
      `正在筛选「${state.statusFilter}」，共 ${rows.length} 条`;
  } else {
    hint.hidden = true;
  }
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
  if (job.url) {
    const link = el("a", null, "岗位链接");
    link.href = job.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    meta.append(link);
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
  }

  /* 操作按钮 */
  const actions = el("div", "card-actions");

  const btnAnalyze = el("button", "ghost small",
    state.analyzing.has(job.id) ? "分析中…" : (job.analyzed_at ? "重新分析" : "AI 分析"));
  // 注意：不要用 job.description 判断——列表响应（JobOut）不含 JD 全文。
  // 缺 JD 时后端会返回 422，前端照常展示它的提示即可。
  btnAnalyze.disabled = state.analyzing.has(job.id);
  btnAnalyze.addEventListener("click", () => analyzeJob(job.id));

  const btnEdit = el("button", "ghost small", "编辑");
  btnEdit.addEventListener("click", () => openForm(job));

  const btnDelete = el("button", "ghost small", "删除");
  btnDelete.addEventListener("click", () => removeJob(job));

  actions.append(btnAnalyze, btnEdit, btnDelete);
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
      "salary_min", "salary_max", "salary_note", "url", "published_at",
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
    // 别抢走用户在输入框里的正常粘贴
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") return;

    const items = event.clipboardData ? event.clipboardData.items : [];
    for (const item of items) {
      if (item.kind === "file" && item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          event.preventDefault();
          importScreenshot(file);
          return;
        }
      }
    }
  });
  $("#btn-cancel").addEventListener("click", closeForm);
  $("#job-form").addEventListener("submit", submitForm);
  $("#btn-prev").addEventListener("click", () => { state.page -= 1; render(); });
  $("#btn-next").addEventListener("click", () => { state.page += 1; render(); });
  $("#filter-status").addEventListener("change", (event) => {
    state.statusFilter = event.currentTarget.value;
    state.page = 1;
    render();
  });
  $("#btn-clear-filter").addEventListener("click", () => {
    state.statusFilter = "";
    state.page = 1;
    $("#filter-status").value = "";
    render();
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
