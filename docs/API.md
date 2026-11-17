# 投递记录服务 · API 接口规范

| 项 | 内容 |
|---|---|
| 版本 | v1.0 |
| 状态 | 设计中（P1 待实现） |
| 最后更新 | 2026-10-21 |
| 对应代码 | `serve.py`（P0 已实现部分） |

---

## 1. 概述

个人及小范围（≤10 人）使用的**求职投递记录工具**，移动端优先。

记录"投了哪些公司、现在走到哪一步"，每次状态变更留一条历史。不做爬虫、不做多租户权限体系、不做 App。

### 功能模块与状态

| 模块 | 说明 | 状态 |
|---|---|---|
| 认证 | 用户名 + 密码换 token | **P1 待实现** |
| 投递记录 | 岗位的增删改查 | ✅ 已实现（无认证版本） |
| 状态历史 | 每次状态变更的流水 | ✅ 已实现 |
| 候选池 | 批量收录 PC 插件抓到的岗位 | P3 规划 |
| 健康检查 | 存活与数据库连通性 | P1 |

---

## 2. 基础 URL

| 环境 | 地址 |
|---|---|
| 本地开发 | `http://127.0.0.1:8000` |
| 局域网（手机访问） | `http://<本机内网IP>:8000` |
| 内网穿透（朋友测试） | `https://<随机子域>.cpolar.top` |

- 所有接口统一前缀：**`/api/v1`**
- 静态页面（手机端 UI）挂在根路径 `/`
- 接口文档：`/docs`（Swagger UI，仅开发环境开启）

**为什么加 `/api/v1`**：将来重构（比如换响应结构、拆模块）时，老客户端仍可用 v1，不必强推升级。

---

## 3. 认证方式

除 `login` 和 `health` 外，**所有接口都需要认证**。

请求头：

```
Authorization: Bearer <token>
```

| 情况 | HTTP 状态码 | code |
|---|---|---|
| 没带 token / token 无效 | `401` | 401 |
| 带了有效 token，但访问不属于自己的资源 | `404` | 404 |

**为什么越权返回 404 而不是 403**：403 等于告诉对方"这个 id 真实存在，只是不归你"，属于信息泄露。用 404 让"不存在"和"不是你的"无法区分。

---

## 4. 响应格式

所有接口返回 JSON，统一结构：

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | integer | **与 HTTP 状态码保持一致**，便于前端只读 body、监控只读状态码 |
| `message` | string | 给人看的提示，成功为 `"success"` |
| `data` | object / array / null | 业务数据，无数据时为 `null` |

### 分页响应的 `data` 结构

```json
{
  "list": [],
  "total": 42,
  "page": 1,
  "page_size": 20,
  "has_more": true
}
```

| 字段 | 说明 |
|---|---|
| `list` | 当前页数据 |
| `total` | 总条数（用于前端算页数） |
| `page` | 当前页码，从 1 开始 |
| `page_size` | 每页条数 |
| `has_more` | 是否还有下一页（`page * page_size < total`） |

### 时间格式

统一使用 **ISO 8601，不带时区**，例如 `2026-10-21T16:12:05`，视为服务器本地时间（当前为 UTC+8）。

> 选不带时区是因为 MySQL 的 `DATETIME` 不存时区；带 `+08:00` 会造成"看起来有时区、实际没有"的误解。将来要跨时区时，改用 `TIMESTAMP` + UTC 并明确标注。

---

## 5. 通用约定

| 约定 | 说明 |
|---|---|
| 字符集 | UTF-8（数据库 `utf8mb4`） |
| 字段命名 | **snake_case**（`page_size`、`from_status`），与数据库列名一致，减少一层映射 |
| 分页参数 | `page`（默认 1，≥1）、`page_size`（默认 20，1–100） |
| 默认排序 | `id` 倒序（最新在前） |
| 空值 | `null`，不使用空字符串代替 |
| 请求体 | `Content-Type: application/json` |
| 未知字段 | 忽略，不报错（便于前后端并行开发） |

> **命名风格的取舍**：参考模板用的是 camelCase（`pageSize`、`categoryId`）。本文档选 snake_case，理由是**与 SQL 列名、Python 变量名一致**——多一层 camelCase 转换就多一处出错的地方。前后端都由你一个人写时，这个理由尤其成立。

---

## 5.1 枚举值约定

**枚举值必须逐字一致**（含大小写），否则筛选会匹配不上：同一个来源写成 `BOSS`、`boss直聘`、`Boss直聘` 会变成三条独立数据。

### 岗位状态 `status`

| 值 | 含义 |
|---|---|
| `待投` | 已看到，还没投 |
| `已投` | 已投递，等回应 |
| `预约面试` | **已约好面试时间，还没面**（配合 `next_interview_at` 字段） |
| `已面试` | 面试结束，等结果 |
| `已挂` | 已明确失败 |

默认 `待投`。**加新状态只需改代码**（`Literal`），不需要改表结构。

### 来源 `source`

| 值 | 含义 |
|---|---|
| `本校` | 学校就业网 / 校招宣讲 |
| `Boss直聘` | Boss 直聘 |
| `自定义` | 其他渠道，具体说明放 `source_detail` |
| `其他` | 兜底（默认值） |

**`source` 限制为这 4 个值**（便于统计与筛选）；自由文本一律放 `source_detail`。

### 单位约定

| 字段 | 单位 | 说明 |
|---|---|---|
| `salary_min` / `salary_max` | **千元 / 月** | 存 `15` 表示 15K；不存 `"15-25K"` 字符串，否则无法排序与筛选 |
| `salary_note` | 自由文本 | `13薪`、`面议`、`含股票` 等无法归入区间的说明 |

---

## 6. 错误码表

| code | 含义 | 典型场景 |
|---|---|---|
| `200` | 成功 | 查询、更新、删除成功 |
| `201` | 创建成功 | `POST` 新增岗位 |
| `400` | 请求不合法 | 业务层判断的参数问题（如页码为负） |
| `401` | 未认证 | 缺 token、token 失效、密码错误 |
| `404` | 资源不存在 | id 不存在，或不属于当前用户 |
| `409` | 冲突 | 同一公司重复记录 |
| `422` | 校验失败 | 字段缺失、类型错、枚举值非法（Pydantic 自动返回） |
| `500` | 服务器内部错误 | 数据库异常、代码 bug |
| `503` | 服务不可用 | 数据库连不上（后续加固用） |

**422 与 400 的分工**：`422` 由框架层（Pydantic）在**进入业务代码之前**返回，`detail` 里带字段级信息；`400` 是业务代码自己判断后返回的。

---

## 7. 接口详情

### 7.0 接口总览（编码清单）

> 按此表从上到下实现，每完成一行部署验证一次。**路径风格决策（2026-10-21）**：认证归 `/auth`，用户资料归 `/users`，业务资源归 `/jobs`——不使用 `/users/login` 这类"资源下塞动作"的写法。

| # | 方法 | 路径 | 说明 | 认证 | 阶段 |
|---|---|---|---|---|---|
| 1 | `GET` | `/api/v1/health` | 健康检查 | 否 | P1 ✅ |
| 2 | `POST` | `/api/v1/auth/login` | 登录，换取 token | 否 | P1 ✅ |
| 3 | `POST` | `/api/v1/auth/register` | 注册（受限开放：开关 + 邀请码） | 否 | P1 ✅ |
| 4 | `GET` | `/api/v1/users/me` | 当前用户 | 是 | P1 ✅ |
| 5 | `GET` | `/api/v1/jobs` | 投递列表（分页/筛选） | 是 | P1 ✅ |
| 6 | `POST` | `/api/v1/jobs` | 新增投递 | 是 | P1 ✅ |
| 7 | `GET` | `/api/v1/jobs/{job_id}` | 单个岗位 | 是 | P1 ✅ |
| 8 | `PATCH` | `/api/v1/jobs/{job_id}` | 修改岗位 | 是 | P1 ✅ |
| 9 | `DELETE` | `/api/v1/jobs/{job_id}` | 删除岗位 | 是 | P1 ✅ |
| 10 | `GET` | `/api/v1/jobs/{job_id}/logs` | 状态历史 | 是 | P1 |
| 11 | `POST` | `/api/v1/auth/logout` | 登出（作废 token） | 是 | P2 规划 |
| 12 | `PUT` | `/api/v1/users/me/password` | 修改密码 | 是 | P2 规划 |

> **进度（2026-11-17）**：1–9 已实现并通过验收，包含"两个账号互相看不到对方数据、越权返回 404"。
>
> **注册的决策变更（2026-11-17）**：原本列为非目标（用户由管理员预建），现改为**受限开放注册**——由 `REGISTER_OPEN` 开关控制是否开放，`REGISTER_CODE` 提供邀请码。默认关闭。理由：管理员预建意味着每次加人都要跑脚本，而给朋友开号的场景本身就需要一个入口；用开关把"开放窗口"限制在几分钟内，风险等同预建。

**建议的实现顺序**：`1 → 2 → 4 → 6 → 5 → 8 → 9 → 10 → 7`

理由：先做健康检查证明"服务能起、库能连"；再登录拿到 token；然后**先做新增**（它带事务，最难，先啃）；列表/详情/改/删可以照着第一个接口的模板复制。

---

### 7.1 认证模块

#### 1. 登录

- **接口地址**：`POST /api/v1/auth/login`
- **是否需要认证**：否
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| name | string | 是 | 用户名（2–20 字符） |
| password | string | 是 | 密码（6–64 字符） |

- **请求示例**：

```json
{ "name": "david", "password": "mypassword" }
```

- **响应示例**：

```json
{
  "code": 200,
  "message": "登录成功",
  "data": {
    "token": "3f2a9c8e7b1d4f60a5c2e9d8b7a6f5e4",
    "user": { "id": 1, "name": "david" }
  }
}
```

- **失败**：

| code | 场景 |
|---|---|
| 401 | 用户名或密码错误（**不区分哪一个错**，避免枚举用户） |
| 422 | 字段缺失或长度不符 |

#### 2. 注册（受限开放）

- **接口地址**：`POST /api/v1/auth/register`
- **是否需要认证**：否
- **准入控制**（两道锁，缺一不可）：

| 配置项 | 位置 | 作用 |
|---|---|---|
| `REGISTER_OPEN` | `.env` | 总开关，默认 `false`。关闭时返回 403，**不再校验邀请码** |
| `REGISTER_CODE` | `.env` | 邀请码，留空则不校验；非空时请求必须带上正确的 `code` |

- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| name | string | 是 | 用户名（2–20 字符）。**规划中**：将来支持邮箱登录时，需禁止含 `@` 以免与邮箱撞名 |
| password | string | 是 | 密码（6–64 字符） |
| code | string | 否 | 邀请码（仅当 `REGISTER_CODE` 非空时必填） |

- **请求示例**：

```json
{ "name": "xiaoming", "password": "mypassword", "code": "TEST1234" }
```

- **响应示例**（成功直接返回 token，省一次登录请求）：

```json
{
  "code": 201,
  "message": "success",
  "data": {
    "token": "OUZTob6PpRq7RU1WRVS9inx_JJhnM3SlU3uL983OtgQ",
    "user": { "id": 3, "name": "xiaoming" }
  }
}
```

- **失败**：

| code | 场景 |
|---|---|
| 403 | 注册未开放（`REGISTER_OPEN=false`） |
| 403 | 邀请码缺失或不正确 |
| 409 | 用户名已被占用 |
| 422 | 字段缺失或长度不符 |

> **为什么开关要排在邀请码前面**：开关关闭时直接拒绝，连邀请码都不校验——这样即使邀请码外泄，只要开关是关的，就没人能注册。日常操作是"开号那几小时打开，开完关掉"。
>
> **为什么 `except IntegrityError` 不能省**：先查重只能挡住"顺序执行"的重复请求。两个请求同时通过查重、再同时插入时，数据库的唯一约束是最后一道防线，捕获它才能返回 409 而不是 500。

#### 3. 获取当前用户

- **接口地址**：`GET /api/v1/users/me`
- **是否需要认证**：是
- **响应示例**：

```json
{
  "code": 200,
  "message": "success",
  "data": { "id": 1, "name": "david", "created_at": "2026-10-21T10:00:00" }
}
```

---

### 7.2 投递记录模块

#### 1. 获取投递列表

- **接口地址**：`GET /api/v1/jobs`
- **是否需要认证**：是（只返回当前用户的记录）
- **请求参数**（query）：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| page | integer | 否 | 页码，默认 1，从 1 开始 |
| page_size | integer | 否 | 每页条数，默认 20，最大 100 |
| status | string | 否 | 按状态筛选：`待投`/`已投`/`预约面试`/`已面试`/`已挂` |

- **请求示例**：

```
GET /api/v1/jobs
GET /api/v1/jobs?page=2&page_size=20&status=预约面试
```

- **响应示例**：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "list": [
      {
        "id": 3,
        "company": "公司C",
        "position": "Python 后端开发实习生",
        "status": "已面试",
        "salary_min": 15,
        "salary_max": 25,
        "source": "Boss直聘",
        "published_at": "2026-10-15",
        "created_at": "2026-10-20T22:03:32"
      }
    ],
    "total": 4,
    "page": 1,
    "page_size": 20,
    "has_more": false
  }
}
```

#### 2. 新增投递记录

- **接口地址**：`POST /api/v1/jobs`
- **是否需要认证**：是
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| company | string | 是 | 公司名，1–100 字符 |
| position | string | 是 | 岗位名，1–100 字符。与 `company` 组合在同一用户下唯一 |
| status | string | 否 | 初始状态，默认 `待投`；枚举见 §5.1 |
| source | string | 否 | 来源，默认 `其他`；枚举见 §5.1 |
| source_detail | string | 否 | 来源补充（平台名、内推人等），≤100 字符 |
| salary_min | integer | 否 | 薪资下限，**千元/月**，≥0 |
| salary_max | integer | 否 | 薪资上限，**千元/月**，≥ `salary_min` |
| salary_note | string | 否 | 薪资备注（`13薪`、`面议`），≤50 字符 |
| url | string | 否 | 原始链接，≤500 字符 |
| published_at | string(date) | 否 | 平台发布时间，格式 `2026-10-15` |
| description | string | 否 | JD 全文（可能数千字） |
| company_business | string | 否 | 公司主营业务，≤200 字符 |
| note | string | 否 | 我的备注 |

- **请求示例**：

```json
{
  "company": "某某科技",
  "position": "Python 后端开发实习生",
  "status": "已投",
  "source": "Boss直聘",
  "salary_min": 15,
  "salary_max": 25,
  "salary_note": "13薪",
  "url": "https://example.com/job/123",
  "published_at": "2026-10-15",
  "description": "岗位职责：……任职要求：……",
  "company_business": "企业级 SaaS"
}
```

- **响应示例**：

```json
{
  "code": 201,
  "message": "创建成功",
  "data": { "id": 5, "company": "公司D", "status": "已投" }
}
```

- **失败**：

| code | 场景 |
|---|---|
| 409 | 该用户下已存在同名公司 |
| 422 | 字段缺失、长度超限、状态值不在枚举内 |

- **服务端行为**：在一个事务内完成「插入 jobs」+「插入状态历史（`-` → 初始状态）」，任一失败全部回滚。

#### 3. 获取单个岗位

- **接口地址**：`GET /api/v1/jobs/{job_id}`
- **是否需要认证**：是
- **路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| job_id | integer | 是 | 岗位 ID |

- **响应示例**：

```json
{
  "code": 200,
  "message": "success",
  "data": { "id": 3, "company": "公司C", "status": "已面试", "created_at": "2026-10-20T22:03:32" }
}
```

- **失败**：`404`（不存在，或不属于当前用户）

#### 4. 修改岗位

- **接口地址**：`PATCH /api/v1/jobs/{job_id}`
- **是否需要认证**：是
- **路径参数**：`job_id`（integer，必填）
- **请求参数**（全部可省略，但至少要给一个）：

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 新状态；与当前状态相同则不写入历史。枚举见 §5.1 |
| company | string | 否 | 新公司名 |
| position | string | 否 | 新岗位名 |
| source | string | 否 | 来源；枚举见 §5.1 |
| source_detail | string | 否 | 来源补充说明 |
| salary_min | integer | 否 | 薪资下限（千元/月） |
| salary_max | integer | 否 | 薪资上限（千元/月） |
| salary_note | string | 否 | 薪资备注 |
| url | string | 否 | 原始链接 |
| published_at | string(date) | 否 | 平台发布时间 |
| description | string | 否 | JD 全文 |
| company_business | string | 否 | 公司主营业务 |
| note | string | 否 | 我的备注 |

> **只有 `status` 变化才会写入 `status_log`**。改公司名、改备注等操作用同一个事务完成，但不产生历史记录——历史表只跟踪"状态流转"。

- **请求示例**：

```json
{ "status": "已面试" }
```

- **响应示例**：

```json
{
  "code": 200,
  "message": "更新成功",
  "data": {
    "id": 3,
    "company": "公司C",
    "status": "已面试",
    "from_status": "预约面试"
  }
}
```

- **失败**：

| code | 场景 |
|---|---|
| 404 | id 不存在或不属于当前用户 |
| 409 | 改公司名时与已有记录重名 |
| 422 | 状态值非法、无任何可改字段 |

- **服务端行为**：一个事务内完成「读旧状态 → 更新 jobs → 写状态历史」。

#### 5. 删除岗位

- **接口地址**：`DELETE /api/v1/jobs/{job_id}`
- **是否需要认证**：是
- **路径参数**：`job_id`（integer，必填）
- **响应示例**：

```json
{ "code": 200, "message": "删除成功", "data": { "deleted_id": 5 } }
```

- **失败**：`404`
- **服务端行为**：一个事务内**先删状态历史，再删岗位**（先子后父，为将来加外键做准备）。

#### 6. 获取状态历史

- **接口地址**：`GET /api/v1/jobs/{job_id}/logs`
- **是否需要认证**：是
- **路径参数**：`job_id`（integer，必填）
- **请求参数**（query）：`page`、`page_size`（同上）
- **响应示例**：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "list": [
      { "id": 2, "from_status": "预约面试", "to_status": "已面试", "created_at": "2026-10-20T22:53:01" },
      { "id": 1, "from_status": "-", "to_status": "已投", "created_at": "2026-10-20T22:03:32" }
    ],
    "total": 2,
    "page": 1,
    "page_size": 20,
    "has_more": false
  }
}
```

- **失败**：`404`（岗位不存在或不属于当前用户）

---

### 7.3 候选池模块（P3 规划，**未实现**）

用于承接 PC 浏览器插件批量上报的岗位。与投递记录的区别：候选池是"看过、可能投"的粗粒度数据，投递记录是"决定投了"的细粒度数据。

| 接口 | 说明 | 状态 |
|---|---|---|
| `POST /api/v1/candidates/batch` | 批量上报（一次 10–50 条），立即返回 `202`，后台异步解析打分 | 未实现 |
| `GET /api/v1/candidates` | 列表，按 AI 评分倒序 | 未实现 |
| `PATCH /api/v1/candidates/{id}` | 标记"采纳"（转为投递记录）或"忽略" | 未实现 |
| `DELETE /api/v1/candidates/{id}` | 删除单条 | 未实现 |

> 本节只列轮廓，等 P3 阶段再补完整字段与示例。**先不实现的理由**：没有插件就没有数据来源，现在设计字段是拍脑袋。

---

### 7.4 健康检查

- **接口地址**：`GET /api/v1/health`
- **是否需要认证**：否
- **响应示例**：

```json
{ "code": 200, "message": "success", "data": { "status": "ok", "db": "ok" } }
```

- 数据库连不上时返回 `503`，`data.db` 为 `"down"`。用途：部署后监控是否存活。

---

## 8. 附录 A：数据库表结构（v1 目标）

```sql
-- 用户
CREATE TABLE users (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(20) NOT NULL UNIQUE,
  password_hash VARCHAR(200) NOT NULL,
  token VARCHAR(64) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 投递记录
CREATE TABLE jobs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,

  -- 岗位主体
  company VARCHAR(100) NOT NULL,
  position VARCHAR(100) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT '待投',

  -- 薪资（单位：千元/月）
  salary_min INT NULL,
  salary_max INT NULL,
  salary_note VARCHAR(50) NULL,

  -- 来源与时间
  source VARCHAR(20) NOT NULL DEFAULT '其他',
  source_detail VARCHAR(100) NULL,
  url VARCHAR(500) NULL,
  published_at DATE NULL,

  -- 内容
  description TEXT NULL,
  company_business VARCHAR(200) NULL,
  note TEXT NULL,

  -- 审计
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uk_user_company_position (user_id, company, position),
  KEY idx_user_status (user_id, status),
  KEY idx_user_published (user_id, published_at)
);

-- 状态历史
CREATE TABLE status_log (
  id INT PRIMARY KEY AUTO_INCREMENT,
  job_id INT NOT NULL,
  from_status VARCHAR(20) NOT NULL,
  to_status VARCHAR(20) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_job (job_id)
);
```

**四处关键设计**：

1. **`UNIQUE (user_id, company, position)` 而不是 `UNIQUE (company)`**——多用户后"公司A"在不同用户那里应该各有一条；加上 `position` 后，同一公司可以投多个岗位。
2. **`KEY (user_id, status)`**——列表查询永远带 `user_id`，索引要让"按用户筛选"走索引而不是全表扫描。
3. **薪资拆成两个整数列**——存 `"15-25K"` 字符串无法排序和范围筛选。
4. **`source` 用 VARCHAR 而不是 ENUM**——加新来源只改代码，不锁表；取值靠 API 层的 `Literal` 约束（见 §5.1）。

**暂不做的两件事**：`jobs.user_id` 暂时没有外键（`users` 表先建）；`status_log.job_id` 同样无外键。等 `User` 模型落地后统一补，并考虑 `ON DELETE CASCADE`。

---

## 9. 附录 B：与参考模板的差异

| 项 | 参考模板 | 本规范 | 原因 |
|---|---|---|---|
| URL 风格 | 动作式 `/api/user/register` | 资源式 `/api/v1/jobs` | 路径只表示资源，动作交给 HTTP 方法 |
| 字段命名 | camelCase | snake_case | 与数据库列名一致，少一层映射 |
| 分页参数 | `page` / `pageSize` | `page` / `page_size` | 同上 |
| 认证头 | `Authorization: token值` | `Authorization: Bearer <token>` | 遵循 HTTP 标准（RFC 6750） |
| 响应包装 | `{code, message, data}` | 同左（但 `code` 与 HTTP 状态码严格一致） | 见下 |

**关于响应包装的取舍**：`{code, message, data}` 是冗余的——HTTP 状态码已经表达了同一件事。但它有两个现实好处：前端只读 body 不必判断 HTTP 层；国内团队和第三方对接方普遍预期这种格式。本项目采用它，并**强制 `code` 等于 HTTP 状态码**，避免出现"HTTP 200 但业务失败"这种最难排查的组合。

---

## 10. 版本策略

- 接口变更遵循 `/api/v1` → `/api/v2`，**不做原地破坏性修改**。
- 新增字段（可选）不算破坏性变更，直接加。
- 删除/改名/改变字段类型算破坏性变更，必须开新版本。
- 本文档随代码同步更新；**文档与代码不一致时，以本文档为准，改代码**。
