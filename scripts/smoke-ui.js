/* 前端冒烟测试：用最小 DOM 桩把「岗位详情页」渲染跑一遍。
 *
 * 为什么需要它：
 *   前端没法跑单元测试，但 "xxx is not defined" 这类错误一上线就是白屏。
 *   曾经因为一次范围删除误删了草稿函数（hasDraft），页面直接白屏。
 *   这个脚本把渲染路径真的跑一遍，能在提交前抓到。
 *
 * 跑法（仓库根目录）：
 *   node scripts/smoke-ui.js
 *
 * 退出码 0 = 三种场景都渲染成功；1 = 有失败。
 */

﻿/* 冒烟测试：用最小 DOM 桩把详情页渲染跑一遍。
   目的不是测样式，而是抓 "xxx is not defined" 这类运行期错误——
   之前 hasDraft 被误删就是这么漏过去的。 */
const fs = require("fs");

function makeNode(tag = "div") {
  const node = {
    tagName: (tag || "div").toUpperCase(),
    className: "", textContent: "", innerHTML: "",
    hidden: false, open: false, disabled: false, rows: 0, maxLength: 0,
    placeholder: "", value: "", type: "text",
    dataset: {}, style: {},
    childNodes: [], parentElement: null,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      contains(c) { return this._set.has(c); },
      toggle(c) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); },
    },
    append(...kids) { for (const k of kids) { if (k && k.parentElement === undefined) k.parentElement = node; node.childNodes.push(k); } },
    appendChild(k) { node.childNodes.push(k); return k; },
    replaceChildren(...kids) { node.childNodes = kids.filter(Boolean); },
    replaceWith() {},
    addEventListener() {}, removeEventListener() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; },
    contains() { return false; },
    getBoundingClientRect() { return { top: 0, bottom: 0, left: 0, right: 0, height: 0, width: 0 }; },
    setAttribute() {}, removeAttribute() {}, remove() {},
    focus() {}, blur() {}, click() {},
  };
  return node;
}

const doc = {
  createElement: makeNode,
  createTextNode: (t) => ({ nodeValue: t, textContent: t }),
  querySelector: () => makeNode(),
  querySelectorAll: () => [],
  getElementById: () => makeNode(),
  addEventListener: () => {},
  removeEventListener: () => {},
  activeElement: null,
  visibilityState: "visible",
  body: makeNode("body"),
};

const store = new Map();
const localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  key: (i) => [...store.keys()][i] ?? null,
  get length() { return store.size; },
  clear: () => store.clear(),
};

const win = {
  scrollBy: () => {}, scrollTo: () => {}, confirm: () => false, alert: () => {},
  addEventListener: () => {}, removeEventListener: () => {},
  matchMedia: () => ({ matches: false, addEventListener: () => {} }),
};

const src = fs.readFileSync("frontend/app.js", "utf8");
const factory = new Function(
  "document", "window", "localStorage", "TextEncoder", "console", "fetch", "navigator", "location",
  src + "\nreturn { renderDetail, renderInterviewPrep, questionCard, practiceBlock, state, questionHash, renderInterviewSection, openInterviewForm, collectInterview };"
);

let api;
try {
  api = factory(doc, win, localStorage, TextEncoder, console, () => Promise.reject(new Error("no fetch")), { userAgent: "node" }, { href: "http://localhost/" });
  console.log("✅ 加载 app.js 未报错");
} catch (err) {
  console.log("❌ 加载失败:", err.message);
  process.exit(1);
}

/* 造一条带多轮练习记录的岗位详情，跑渲染 */
const job = {
  id: 15,
  company: "星辰科技",
  position: "Python 后端开发实习生",
  status: "待投",
  source: "Boss直聘",
  source_detail: null,
  salary_min: 15, salary_max: 25, salary_note: "13薪",
  url: null, apply_url: "https://example.com/apply",
  published_at: "2026-10-08",
  created_at: "2026-11-25T11:15:00",
  next_interview_at: null,
  company_business: "企业级 SaaS",
  description: "任职要求：熟练掌握 Python、FastAPI、MySQL。",
  note: "HR 说随时可以投",
  match_score: 88,
  verdict: "推荐投递",
  analyzed_at: "2026-11-25T11:15:00",
  analysis: null,
  interview_prep: JSON.stringify({
    questions: [
      {
        question: "你的 Agent Loop 里退出时机由模型决定，这在实际运行中会不会死循环？",
        basis: "resume",
        basis_quote: "退出时机由模型决定而非代码控制",
        why_asked: "验证边界控制能力",
        your_status: "ok",
        reference_answer: "讲三层兜底：超时、截断、调用计数。",
        follow_up: "超时设多少？",
        key_points: ["子进程超时 120 秒", "输出截断 5 万字符", "PreToolUse 钩子调用计数"],
      },
      {
        question: "你们的 Redis 缓存一致性怎么保证？",
        basis: "jd",
        basis_quote: "熟悉 MySQL、Redis",
        why_asked: "验证真实项目深度",
        your_status: "gap",
        reference_answer: "延迟双删 + TTL 兜底。",
        follow_up: "",
        key_points: ["先更新库再删缓存", "延迟双删的局限", "TTL 兜底"],
      },
    ],
    gaps_summary: ["消息队列零经验"],
    prep_advice: "先补 gap 再练深挖。",
  }),
  interview_prep_at: "2026-11-26T10:00:00",
};

/* 注入作答记录（含原题 + 两层追问，其中最后一层待答） */
api.state.detailId = 15;
const hash = api.questionHash(job.interview_prep ? JSON.parse(job.interview_prep).questions[0].question : "");
api.state.answers = new Map([
  [hash, {
    question_hash: hash,
    status: "partial",
    depth: 2,
    covered: [0],
    wrong: [{ index: 2, why: "顺序说反了" }],
    missing: [1],
    answer: "我加了超时。",
    transcript: [
      { layer: "0", question: JSON.parse(job.interview_prep).questions[0].question, answer: "我加了超时。", evaluation: { covered: [0], wrong: [], missing: [1, 2], verdict: "太简略" } },
      { layer: "1", question: "超时设多少秒？", answer: "120 秒。", evaluation: { covered: [0], wrong: [], missing: [1, 2], verdict: "没提截断" } },
      { layer: "2", question: "截断怎么处理？", answer: null },
    ],
    finish_reason: null,
    verdict: "没提截断",
  }],
]);
/* 造两份未保存的草稿，覆盖草稿提醒/角标路径 */
localStorage.setItem("draft:15:" + hash + ":1", "改过的答案");

/* 造一条面试复盘记录，覆盖「详情页面试记录区块」的渲染 */
api.state.interviews = [
  {
    id: 1,
    job_id: 15,
    interview_at: "2026-11-27T14:00:00",
    round_no: 1,
    outcome: "failed",
    summary: "整体偏紧，Redis 一致性答虚了。",
    created_at: "2026-11-27T20:00:00",
    updated_at: "2026-11-27T20:00:00",
    questions: [
      { id: 1, question: "Agent Harness 的权限怎么设计的？", my_answer: "说了三级闸门。", performance: "ok", gap: "凭证生命周期", follow_up: "路径穿越怎么防？" },
      { id: 2, question: "Redis 缓存不一致怎么处理？", my_answer: "只说了先删缓存。", performance: "bad", gap: "延迟双删 + TTL", follow_up: null },
    ],
  },
];

const cases = [
  ["有练习记录 + 草稿", job],
  ["没有 interview_prep", { ...job, interview_prep: null, interview_prep_at: null }],
  ["有 prep 但没练过", { ...job, interview_prep: job.interview_prep }],
];

let failed = 0;
api.state.answers = new Map();   // 第三种情况用空记录
for (const [name, data] of cases) {
  try {
    if (name.includes("没练过")) api.state.answers = new Map();
    else api.state.answers = new Map([[hash, { question_hash: hash, status: "partial", depth: 2, covered: [0], wrong: [], missing: [1, 2], answer: "我加了超时。", transcript: [
      { layer: "0", question: JSON.parse(job.interview_prep).questions[0].question, answer: "我加了超时。", evaluation: { covered: [0], wrong: [], missing: [1, 2], verdict: "太简略" } },
      { layer: "1", question: "超时设多少秒？", answer: "120 秒。" },
      { layer: "2", question: "截断怎么处理？", answer: null },
    ], finish_reason: null }]]);
    api.renderDetail(data);
    console.log(`✅ 渲染通过：${name}`);
  } catch (err) {
    failed += 1;
    console.log(`❌ 渲染失败：${name} → ${err.message}`);
    console.log("   ", (err.stack || "").split("\n")[1] || "");
  }
}

/* 录入表单：新建模式 / 编辑模式 */
for (const [label, record] of [["新建面试记录", null], ["编辑面试记录", api.state.interviews[0]]]) {
  try {
    api.openInterviewForm(15, record);
    console.log(`✅ 渲染通过：${label}`);
  } catch (err) {
    failed += 1;
    console.log(`❌ 渲染失败：${label} → ${err.message}`);
  }
}

process.exit(failed ? 1 : 0);
