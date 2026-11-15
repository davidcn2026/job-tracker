# 投递记录服务 · 技术架构与技术栈决策

| 项 | 内容 |
|---|---|
| 版本 | v1.0 |
| 最后更新 | 2026-10-21 |
| 对应文档 | `docs/API.md` |

---

## 1. 项目定位（决定了后面所有取舍）

> **个人及小范围（≤10 人）使用的求职投递记录工具，移动端优先，不做商业产品。**

由此推出四条硬约束，所有技术选择都必须服从它们：

| 约束 | 推论 |
|---|---|
| 用户 ≤10 人，无增长诉求 | 不需要微服务、不需要缓存层、不需要消息队列 |
| 单人开发、单人运维 | 技术选型必须"一个人看得懂、改得动" |
| 求职作品属性 | **代码可读性和文档价值 > 性能**；每个技术选择要能讲出理由 |
| 不碰招聘平台数据 | 不做爬虫，数据来源是用户主动提供 |

---

## 2. 技术栈总览

| 层 | 选型 | 版本 |
|---|---|---|
| 语言 | Python | 3.13 |
| Web 框架 | FastAPI | 最新稳定版 |
| 数据校验 | Pydantic | v2（FastAPI 自带） |
| ASGI 服务器 | Uvicorn | 最新稳定版 |
| 数据库 | MySQL | 8.0 |
| 数据库驱动 | aiomysql | 异步 MySQL 驱动（基于 PyMySQL，纯 Python，免编译） |
| ORM | SQLAlchemy 2.0（`asyncio` 扩展） | async session + 自带连接池 |
| 连接管理 | SQLAlchemy 引擎内置连接池 | `pool_size` / `pool_recycle` / `pool_pre_ping` |
| 迁移管理 | 开发期 `create_all` + 手动 `ALTER`；有真实数据后切 Alembic | 见 D9 |
| 密码哈希 | `hashlib.scrypt`（标准库） | — |
| 认证 | Bearer Token（存 `users.token`） | — |
| 配置 | `python-dotenv` + `.env` | — |
| 前端 | 原生 HTML + CSS + JS（fetch），PWA manifest | 无构建工具 |
| 测试 | pytest + `pytest-asyncio` + `httpx.AsyncClient` | P2 引入 |
| 日志 | `logging` + `basicConfig`（终端）；部署后加 `FileHandler` + 轮转 | — |
| 进程管理 | systemd（云主机）/ 内网穿透（测试期） | P2 |
| 反向代理 | Nginx | P2 |
| 依赖管理 | pip + `requirements.txt` | — |

---

## 3. 逐项决策与理由

### D1. 框架：FastAPI（否决 Django / Flask）

| 理由 | 说明 |
|---|---|
| 自带接口文档 | `/docs` 直接可点，省掉写 Postman 集合和手工文档 |
| 自带请求校验 | Pydantic 在入口挡住非法输入，业务代码不用写一堆 `if not` |
| 类型标注即配置 | 一处标注同时决定了：参数来源、类型转换、校验规则、文档展示 |
| 异步能力 | 将来加 LLM 调用（候选池打分）时不会卡住线程 |

**否决 Flask**：文档、校验、依赖注入全要自己搭，等于重写一遍 FastAPI 的轮子。
**否决 Django**：ORM + Admin + 模板体系对 4 个接口的项目是巨大负担，而且面试时"我用 Django 的 Admin 生成了后台"证明不了什么。

### D2. 数据库：MySQL 8.0（否决 SQLite / PostgreSQL）

| 理由 | 说明 |
|---|---|
| 岗位匹配 | 抽样 24 条 JD 中，要求 MySQL/关系库的有 7 条；Docker 4 条 |
| 并发可用 | 多用户 + 手机同时访问，SQLite 的单写锁会成瓶颈 |
| 学习价值 | 库/表/索引/外键/事务/权限，MySQL 是完整的教科书 |

**否决 SQLite**：单文件、无用户体系、单写者锁——它适合本地工具，不适合"放在服务器上给几个朋友用"。
**否决 PostgreSQL**：技术上更好（严格、`JSONB`、窗口函数），但岗位要求里出现频率远低于 MySQL。**先匹配岗位，再谈技术优越性。**

### D3. 数据访问：SQLAlchemy 2.0 async ORM（2026-10-21 决策变更）

> **变更记录**：初版决定"手写 SQL + PyMySQL，暂不上 ORM"。后决定跟随教程路线走异步 ORM，故改为
> SQLAlchemy 2.0 + aiomysql。这是一次**主动的路线切换**，不是小调整——原方案的同步 `pymysql` 代码
> **不再兼容**，4 个接口需要重写。

| 理由 | 说明 |
|---|---|
| 对齐主流做法 | 岗位 JD 里 SQLAlchemy / ORM 的出现频率高于"手写 SQL" |
| 减少样板 | 增删改查、分页、关联查询由 ORM 生成 |
| 类型安全 | 模型字段有类型标注，IDE 能补全、能查错 |
| 自带连接池 | 不用再自己包 `DBUtils` |
| 异步 | 配合 async 路由，阻塞问题从根上消失 |

**代价（必须承认）**：

1. **看不到 SQL** → 分析慢查询要靠 `echo=True` 或 `EXPLAIN`，不能像以前一样"读代码就知道查了什么"
2. **越权风险变成"忘记加过滤条件"** → 所有查询必须收进 `crud/`，routers 里不许直接写 `select()`
3. **同步/异步不能混用** → 旧代码整体替换，不能两套并存

**红线**：一个项目里**只允许一种数据访问方式**。混用会让事件循环被同步 IO 阻塞，且事务边界失控。

### D4. 连接管理：SQLAlchemy 引擎内置连接池

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,           # 常驻连接数
    max_overflow=10,       # 峰值最多再开 10 条
    pool_recycle=3600,     # 1 小时回收
    pool_pre_ping=True,    # 取连接前探活
)
```

| 参数 | 作用 | 不配的后果 |
|---|---|---|
| `pool_size` | 常驻连接数 | 默认 5，够用 |
| `max_overflow` | 峰值可临时超出多少 | 并发高时报 `QueuePool limit overflow` |
| `pool_recycle` | 连接最长存活秒数 | **必配**：MySQL 默认 8 小时断开空闲连接，池里会留死连接 → 随机 500 |
| `pool_pre_ping` | 取用前先 ping | 不加则 `recycle` 也可能漏掉死连接 |

后两条是**生产事故的常见来源**，不是可选优化。

### D5. 认证：Bearer Token 存表（否决 JWT / Session）

| 方案 | 结论 |
|---|---|
| **Bearer Token 存 `users.token`** | ✅ 选它。实现 20 行，一次查询验完，方便随时吊销（改库即可） |
| JWT | ❌ 无状态听起来好，但**吊销困难**（要维护黑名单），对本项目是负收益 |
| Session + Cookie | ❌ 手机浏览器 + 内网穿透场景下，Cookie 的域名/跨域问题会消耗大量时间 |

**安全下限（不可妥协）**：密码用 `hashlib.scrypt` 加盐哈希存储，**绝不存明文**；登录失败不区分"用户不存在"和"密码错"。

### D6. 响应格式：`{code, message, data}`

**这是本规范里唯一有争议的决定。** HTTP 状态码已经表达成败，body 再写一遍 `code` 是冗余。

选它的理由：前端（尤其手写 JS）只读 body 就够了；与参考模板、国内常见约定一致，将来别人接手不用适应。
**代价与防线**：强迫 `code` 严格等于 HTTP 状态码，严禁出现"HTTP 200 + body code 500"。

### D7. 前端：原生 HTML + fetch，无框架

| 理由 | 说明 |
|---|---|
| 移动端只需要"看 + 改状态" | 一个列表页 + 几个按钮，Vue/React 是杀鸡用牛刀 |
| 无构建链 | 没有 npm / webpack / vite，改完刷新即生效，手机直接访问 |
| PWA | 加一个 `manifest.json` 就能"添加到主屏幕"，体验接近 App |
| 学到的东西通用 | HTML/CSS/`fetch`/`localStorage` 是任何前端框架的基础 |

**否决 Streamlit**：它是另一套服务端渲染框架，会和现有 FastAPI 变成两个应用；且它做"表单提交"类的交互很别扭。

### D8. 部署：两阶段（隧道 → 云主机）

| 阶段 | 方案 | 成本 | 用途 |
|---|---|---|---|
| P2-a | 内网穿透（cpolar/ngrok 免费版） | 0 元 | 让朋友能打开，收测试反馈 |
| P2-b | 云主机 + Nginx + systemd | 约 50 元/月 | 24 小时可用，能写进简历 |

**先隧道后机器**：现在还没到"24 小时稳定"的阶段，先验证功能；否则你会花时间在服务器运维上，而不是产品本身。

**安全红线**：`3306` 永不对公网开放；数据库只听 `127.0.0.1`。

### D9. 迁移：开发期 `create_all`，有真实数据后切 Alembic

| 阶段 | 做法 | 前提 |
|---|---|---|
| 开发期（现在） | `Base.metadata.create_all()` 建表；改结构时**手动 `ALTER TABLE`** | 表里没有不可丢的数据 |
| 有真实数据后 | 引入 Alembic：`alembic revision --autogenerate` | 必须有可回滚的迁移记录 |

**必须知道的坑**：`create_all()` 只执行 `CREATE TABLE IF NOT EXISTS`，**永远不会 `ALTER` 已存在的表**。
所以"改了模型 → 重启 → 没生效"是必然结果，不是 bug。改结构只有两条路：手动 `ALTER TABLE`，或用 Alembic。

**手写 `ALTER` 的三步法**（给已有数据的表加 `NOT NULL` 列）：

```sql
ALTER TABLE jobs ADD COLUMN user_id INT NULL;         -- 1. 先放宽
UPDATE jobs SET user_id = 1 WHERE user_id IS NULL;    -- 2. 填满
ALTER TABLE jobs MODIFY COLUMN user_id INT NOT NULL;  -- 3. 再收紧
```

直接 `ADD COLUMN ... NOT NULL` 会在已有数据上失败——这是新手最常踩的迁移坑。

### D10. 日志：先终端，后文件

P1 用 `basicConfig` 输出到终端；**部署到服务器时**再加 `FileHandler` + `TimedRotatingFileHandler`（按天切、保留 7 天）。

**为什么不是现在就加**：本机调试时终端够用，提前加只会多一个要维护的文件。

---

## 4. 目标目录结构（P1 达成）

```
job-tracker/                 # 已从 learn/ 改名
├── app/
│   ├── main.py              # FastAPI 实例、路由挂载、静态目录、异常处理器
│   ├── core/
│   │   ├── config.py        # 读 .env（Settings）
│   │   ├── security.py      # 密码哈希、token 生成
│   │   └── logging.py       # 日志配置
│   ├── db/
│   │   ├── session.py       # create_async_engine + async_sessionmaker
│   │   └── base.py          # DeclarativeBase（模型基类）
│   ├── models/              # ORM 模型（= 数据库表）
│   │   ├── user.py
│   │   └── job.py           # Job + StatusLog
│   ├── schemas/             # Pydantic 模型（请求/响应）
│   │   ├── common.py        # Resp[T] 统一响应
│   │   ├── auth.py
│   │   └── job.py
│   ├── crud/                # 所有查询都在这里（越权检查的唯一入口）
│   │   ├── user.py
│   │   └── job.py
│   ├── deps.py              # get_session / current_user
│   └── routers/             # 只解析请求、调 crud、返回响应
│       ├── auth.py
│       ├── jobs.py
│       └── health.py
├── static/
│   ├── index.html           # 手机端主页面
│   ├── app.js
│   ├── style.css
│   └── manifest.json        # PWA
├── tests/
├── docs/
│   ├── API.md
│   └── ARCHITECTURE.md
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

**分层原则（改用 ORM 后更要守）**：

| 层 | 只做一件事 | 禁止 |
|---|---|---|
| `routers` | 解析请求、调 `crud`、返回响应 | **不许出现 `select()` / `session.execute()`** |
| `crud` | 所有数据库查询 | 不许抛 `HTTPException`（返回 `None`，由 router 转成 404） |
| `models` | 表结构与关系 | 不许放业务逻辑 |
| `schemas` | 请求/响应结构 | 不许 import `models` |

**为什么"routers 里不许写查询"是硬规定**：越权检查（`where(Model.user_id == user.id)`）只可能在 `crud` 层统一保证。一旦允许 router 里随手写一句 `select()`，就一定会漏。

---

## 5. 演进阶段与完成标准

| 阶段 | 内容 | 完成标准（可验证） |
|---|---|---|
| **P0** ✅ | CRUD + 事务 + 校验 + 分页 + 日志 | 已完成，`/docs` 可跑通全部接口 |
| **P1** | 重写为 async SQLAlchemy + 多用户 + token 登录 + 统一响应 + `/api/v1` | 两个账号互相看不到对方数据；越权返回 404；错误响应也是 `{code,message,data}` |
| **P2** | 手机页面 + pytest（async）+ 内网穿透 + 文件日志 | 朋友手机能打开并改一条记录；`pytest` 全绿 |
| **P3** | 候选池 + 批量上报 + 异步打分 | 能批量导入 20 条并给出评分排序 |
| **P4** | Chrome 插件（列表页收录） | 在真实招聘网站上点一次，入库 20 条 |

---

## 6. 明确不做的事（非目标）

| 不做 | 理由 |
|---|---|
| 爬虫 / 自动抓取 | 违反平台协议、反爬对抗成本高、法律风险；合规通道不存在 |
| 微服务 / 容器编排（K8s） | 10 个用户的项目，运维复杂度是纯负收益 |
| 原生 App / 小程序 | 网页 + PWA 已满足"手机上能用"；上架成本和审核是纯消耗 |
| 多租户 / 复杂权限体系 | 用户 ≤10 人，token + `user_id` 过滤足够 |
| 用户注册/找回密码 | 用户由管理员预建，10 个人不需要自助流程 |
| 消息队列 / Redis | 当前没有异步任务和缓存需求；P3 若需异步，先用 FastAPI `BackgroundTasks` |

---

## 7. 决策确认状态

| # | 决策 | 状态 | 说明 |
|---|---|---|---|
| 1 | **响应加包装 `{code, message, data}`** | ✅ 已确认 | 实现方式：Pydantic 泛型 `Resp[T]` + `response_model`，并**必须配 `HTTPException` 异常处理器**，否则错误响应仍是 `{"detail": ...}` |
| 2 | **URL 加 `/api/v1` 前缀** | ⏳ 待确认 | 对移动端**无影响**（前缀只是路径的一段）；唯一影响是已保存的 URL/书签失效 |
| 3 | **目录从 `learn/` 改名为 `job-tracker/`** | ✅ 已完成 | 2026-10-21 已重命名 |
| 4 | **数据访问改为 SQLAlchemy 2.0 async ORM** | ✅ 已确认 | 2026-10-21 路线切换，旧的同步 `pymysql` 代码整体重写（见 D3） |

**关于第 1 项的关键补充**：`response_model` 只作用于成功路径。若不加 `@app.exception_handler(HTTPException)`，
`404/409/500` 的响应体仍是 FastAPI 默认的 `{"detail": ...}`，与统一格式不一致——这是"统一响应"最常漏的一步。

---

## 8. 已知风险

| 风险 | 应对 |
|---|---|
| ORM 查询漏 `user_id` 过滤 → 越权 | 所有查询只能写在 `crud/`，routers 禁止出现 `select()`；测试里专门加"跨用户访问"用例 |
| 同步 `pymysql` 与 async ORM 混用 | 业务代码一律不 `import pymysql`；`aiomysql` 内部会用到它，但那是驱动层的事 |
| 招聘网站 DOM 改版 → 插件失效（P4） | 用 LLM 解析替代硬编码选择器；接受"需要持续维护"这个成本 |
| 内网穿透域名不固定 | 测试期接受；P2-b 上云主机后固定 |
| 单人维护，长期断更 | 用本文档记录决策，让"半年后的你"能快速捡起来——这也是写它的原因 |
