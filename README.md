# 投递记录服务

> **状态**：P0（单用户 CRUD + 事务）已完成并验证；**P1 重构中**——多用户 + async SQLAlchemy + `/api/v1` + 统一响应。
> P0 的同步 `pymysql` 版本已归档到 `legacy/`，仅作对照，不参与运行。
>
> **文档索引**：[接口规范](docs/API.md) · [技术架构与决策](docs/ARCHITECTURE.md)

## 1. 这是什么

记录我投了哪些公司、现在走到哪一步（待投 / 已投 / 面试中 / 已面试）。

**解决什么问题**：投递多了以后，Excel 记不住“这家我到底投没投、上次聊到哪一步”。
这个服务让我在手机上就能查、能改状态，并且**每次状态变更都留下一条记录**——
面试前翻一眼就知道某家公司什么时候投的、几号面的。

## 2. 技术栈

> 下表是 **P0 实际使用**的技术。P1 目标栈（SQLAlchemy 2.0 async + aiomysql + pydantic-settings）
> 与取舍理由见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

| 组件 | 用途 |
|---|---|
| Python 3.13 | 语言 |
| FastAPI | 提供 HTTP 接口，自带 `/docs` 交互文档 |
| Uvicorn | 运行 FastAPI 的服务器 |
| PyMySQL | 连接 MySQL 的驱动 |
| python-dotenv | 从 `.env` 读取数据库配置 |
| MySQL 8.0.46 | 存储数据 |

## 3. 怎么跑起来

### 3.1 启动数据库

```powershell
net start MySQL80
```

### 3.2 建库建表

在 `mysql` 客户端里执行：

```sql
CREATE DATABASE learn CHARACTER SET utf8mb4;
USE learn;

CREATE TABLE jobs (
  id INT PRIMARY KEY AUTO_INCREMENT,
  company VARCHAR(100) NOT NULL UNIQUE,
  status VARCHAR(20) NOT NULL DEFAULT '待投'
);

CREATE TABLE status_log (
  id INT PRIMARY KEY AUTO_INCREMENT,
  job_id INT NOT NULL,
  from_status VARCHAR(20) NOT NULL,
  to_status VARCHAR(20) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 装依赖

```powershell
python -m pip install fastapi uvicorn pymysql python-dotenv
```

### 3.4 配 `.env`

把 `.env.example` 复制成 `.env`，填入自己的数据库密码：

```powershell
Copy-Item .env.example .env
```

`.env` 已被 `.gitignore` 排除，不会进版本库；仓库里只留占位符 `DB_PASSWORD=<你的密码>`。

### 3.5 启动

```powershell
python -m uvicorn serve:app --host 0.0.0.0 --port 8000 --reload
```

- 本机打开：`http://127.0.0.1:8000/docs`
- 手机打开（同一 WiFi）：先用 `ipconfig` 查 WLAN 的 IPv4，再访问 `http://<那个IP>:8000/docs`
- `--host 0.0.0.0` 是手机能访问的前提；只写 `127.0.0.1` 的话手机一定打不开
- `--reload` 只在开发时用，正式部署要关掉

## 4. 接口

> **本节是 P0（单用户）版本的记录，没有认证模块。**
> **完整接口规范——含用户登录、`/api/v1` 前缀、统一响应结构 `{code, message, data}`、状态码约定——见 [docs/API.md](docs/API.md)。**
> 本节在 P1 完成后会删除，避免两处文档不一致。

| 方法 | 路径 | 请求体 | 成功 | 失败 |
|---|---|---|---|---|
| `GET` | `/jobs` | 无 | `200` `[{"id":1,"company":"公司A","status":"已投"}]` | — |
| `POST` | `/jobs` | `{"company":"公司D","status":"已投"}` | `200` `{"ok":true,"id":4}` | `422` 字段缺失或类型错 / `409` 重复公司 / `500` 数据库错误 |
| `PATCH` | `/jobs/{job_id}/status` | `{"status":"已面试"}` | `200` `{"ok":true,"id":3,"from":"面试中","to":"已面试"}` | `404` id 不存在 / `422` 请求体类型错 / `500` 数据库错误 |
| `DELETE` | `/jobs/{job_id}` | 无 | `200` `{"ok":true,"deleted_id":3}` | `404` id 不存在 / `500` 数据库错误 |

**三个写接口都在一个事务里完成：**

- `POST`：插入 `jobs` + 插入 `status_log`，两句一起成败
- `PATCH`：读原状态 → 更新 `jobs` → 写 `status_log`，三句一起成败
- `DELETE`：先删 `status_log` 再删 `jobs`（先子后父），两句一起成败

失败时 `rollback()`，不会留下“改了一半”的数据。

> 注：按 REST 惯例，`POST` 创建成功应返回 `201`，当前返回 `200`，属待改进项。

## 5. 数据库设计

```sql
jobs        id, company, status
status_log  id, job_id, from_status, to_status, created_at
```

| 表 | 存什么 |
|---|---|
| `jobs` | **当前状态**：一个岗位一行 |
| `status_log` | **历史流水**：一次状态变更一行 |

**为什么要两张表？**

`jobs` 只能存“现在是什么状态”，存不下“怎么走到这一步的”。
面试官问“这家什么时候投的、几号面的”，`jobs` 答不了，`status_log` 能答。
这是“**主表存现状、流水表存历史**”的常见拆分。

`status_log.job_id` 指向 `jobs.id`，两张表靠它关联：

```sql
SELECT l.created_at, l.from_status, l.to_status, j.company
FROM status_log l
JOIN jobs j ON l.job_id = j.id
WHERE l.job_id = 3
ORDER BY l.created_at;
```

## 6. 已知限制

| 限制 | 为什么是问题 | 打算怎么改 |
|---|---|---|
| 没有身份验证 | 谁能访问这个网址，谁就能改数据 | 加 API Key 或登录态 |
| 每次请求新建连接 | 并发一高就 `Too many connections` | 上连接池（或 SQLAlchemy） |
| 没有分页 | 表大了 `SELECT *` 会撑爆内存 | 加 `LIMIT/OFFSET` |
| `status_log` 靠代码手动删 | 若绕过 `delete_job()` 直接删 `jobs`，会留下孤儿日志 | 加外键 + `ON DELETE CASCADE`，让数据库自动级联 |
| `status` 在数据库层没有约束 | API 层已用 `Literal` 拦住非法值；但直接写库（或将来别的服务）仍能写入任意字符串 | 数据库改成 `ENUM`，或在 SQL 层加 `CHECK` |
| `status_log.job_id` 无外键 | 可能插入不存在的岗位，产生孤儿数据 | 加 `FOREIGN KEY` |
| 没有测试 | 改代码全靠手点，不敢重构 | 用 `pytest` 覆盖三个接口 |

## 7. 踩过的坑（真实记录）

**1. MySQL 的 root 密码“改了不生效”**

- 现象：改完密码，重启服务后又变回旧密码。
- 根因：`my.ini` 里有一行 `init-file=C:/mysql-init.txt`，每次启动都会执行这个文件里的
  `ALTER USER ... IDENTIFIED BY ...`，把密码重置回去。
- 教训：**改配置前先备份，改完立刻验证**（读一遍文件、重启一次确认）。配置文件里的
  `init-file` 这类"启动时执行"的选项，优先级高于你以为的一切。

**2. 命令行参数里的中文路径被截断**

- 现象：`--init-file="D:\python\后端\reset.sql"` 传进去，报错说文件 `D:\python\` 不存在。
- 根因：路径里的中文在传给原生程序时被丢掉，只剩前半截。
- 教训：**工具报“文件找不到”而你确信路径没错时，先怀疑中文或空格**。

**3. 把客户端错误当成了服务器错误**

- 现象：访问不存在的 id，页面显示 `500 Internal Server Error`。
- 根因：只写了一个 `except Exception`，把本该是 `404` 的情况也包成了 `500`。
- 教训：**`404` 是客户端的错，`500` 才是服务器的错**；异常要按具体类型分支，
  且“具体”的 `except` 必须写在“笼统”的前面。

**4. GUI 的表列表是缓存**

- 现象：`CREATE TABLE` 成功了，Workbench 的树里看不到。
- 根因：Workbench 显示的是上次同步的快照，不是实时状态。
- 教训：**`SHOW TABLES;` 才是数据库此刻的真相**，别急着怀疑自己没建成功。

## 8. 设计决策

| 选择 | 为什么 |
|---|---|
| FastAPI 而不是 Flask / Django | 自带 `/docs` 交互文档和请求体校验，写接口时省掉大量样板代码；对“照着 JD 学后端”的进度来说，能立刻看到结果 |
| 手写 SQL 而不是 ORM | 先看清每一句 SQL 到底做了什么（索引、事务、JOIN），再用 ORM 才知道它替我省了什么；ORM 之后会加，但不是现在 |
| 两张表而不是一张 | 现状和历史分开存：`jobs` 只保证“当前对不对”，`status_log` 保证“过程查得到” |
| 配置放 `.env` 而不是写死在代码里 | 代码要进 git、要给面试官看，密码绝不能跟着走 |