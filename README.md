# 投递记录服务

> **状态**：P1 已完成——多用户认证（Bearer token）、jobs 五接口、统一响应与全局异常处理、
> AI 岗位匹配分析（四档投递建议）、Docker 容器化（含 compose 一键起全套）。
> 未做：状态历史、前端页面、状态变更流水。
>
> **文档索引**：[接口规范](docs/API.md) · [技术架构与决策](docs/ARCHITECTURE.md) · [待办与已定决策](docs/BACKLOG.md)

## 1. 这是什么

记录我投了哪些公司、现在走到哪一步（待投 / 已投 / 预约面试 / 已面试 / 已挂）。

**解决什么问题**：投递多了以后，Excel 记不住"这家我到底投没投、上次聊到哪一步"。
这个服务让我在手机上就能查、能改状态，并且**能对岗位 JD 跑一次 AI 匹配分析**——
给出"推荐投递 / 可考虑投递 / 可以投递 / 不建议投递"的建议，以及缺失的核心能力。

## 2. 技术栈

> 与取舍理由见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，接口约定见 [docs/API.md](docs/API.md)。

| 组件 | 用途 |
|---|---|
| Python 3.13 | 语言 |
| FastAPI | 提供 HTTP 接口，自带 `/docs` 交互文档 |
| Uvicorn | 运行 FastAPI 的服务器 |
| **SQLAlchemy 2.0（async）+ aiomysql** | 异步 ORM 与 MySQL 驱动 |
| **Pydantic v2 / pydantic-settings** | 请求校验、统一响应、配置读取 |
| **OpenAI SDK（指向 DeepSeek）** | AI 匹配分析 |
| MySQL 8.0.46 | 存储数据 |
| Docker + Compose | 容器化部署（应用 + 数据库） |
| pytest / ruff | 测试与静态检查（ruff 已接入） |


## 3. 怎么跑起来

### 3.1 最快：Docker Compose（推荐）

一条命令起完整服务（应用 + MySQL + 自动建表）：

```powershell
Copy-Item .env.example .env      # 然后填 DB_ROOT_PASSWORD / DB_APP_PASSWORD / DEEPSEEK_API_KEY
docker compose up -d --build
```

**它做了什么**：

1. 起一个 `mysql:8.0` 容器，首次启动时**按文件名顺序自动执行 `migrations/001~006`**，建出完整表结构
2. 起应用容器（非 root 用户 `appuser`），等数据库 `healthy` 后才启动
3. 应用通过服务名 `db` 连接数据库（容器网络内部 DNS），**不使用 root 账号**

首次跑完后创建第一个用户（容器里没有注册开关时用这个）：

```powershell
docker compose exec app python create_user.py zyp1 你的密码
```

打开 <http://127.0.0.1:8000/>（前端界面）或 <http://127.0.0.1:8000/docs>（接口文档）验证。

想先塞 10 条演示数据看看界面效果：

```powershell
docker compose cp seed_jobs.py app:/app/seed_jobs.py
docker compose exec app python seed_jobs.py
```

> ⚠️ **注意：容器里的 MySQL 和宿主机的 MySQL 是两个独立的库。**
> 你在宿主机 `job_tracker` 库里已有的数据，容器里**看不到**——容器用的是自己的 `db_data` 卷，
> 只由 `migrations/` 初始化。想把宿主机数据迁过来要单独 `mysqldump` + 导入。

常用命令：

```powershell
docker compose ps                  # 看状态
docker compose logs -f app         # 跟踪应用日志
docker compose down                # 停止（数据保留在 db_data 卷里）
docker compose down -v             # 停止并删除数据卷（会清空数据库）
```

> **注意**：`docker compose down -v` 之后再 `up`，`migrations` 会重新执行一遍——这正好说明迁移文件是自洽的。

### 3.2 本地开发（改代码即时生效）

日常写代码**不要走镜像重建**（改一行要等构建）。有两种方式：

**方式 A：容器里开发（挂载源码 + 热重载）**

仓库里的 `compose.override.yaml` 会自动被加载，所以直接：

```powershell
docker compose up -d
```

此时 `app/`、`frontend/`、`static/` 是 **bind mount** 挂进容器的：
- 改前端 → **刷新浏览器即可**，连重启都不需要
- 改后端 `.py` → uvicorn `--reload` 自动重启（约 1 秒）

> `WATCHFILES_FORCE_POLLING=true` 是必须的：Windows 上的 bind mount 不会可靠传递文件变更事件，
> 靠 inotify 的热重载会失灵，只能改成轮询。

**方式 B：完全不用 Docker（最快）**

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

连宿主机 MySQL（`.env` 里 `DB_HOST=127.0.0.1`），改代码 0.2 秒生效。

> ⚠️ **`compose.override.yaml` 只用于开发。** 生产环境必须显式指定文件，否则会变成热重载 + 挂载源码：
> ```bash
> docker compose -f compose.prod.yaml up -d
> ```
> 一旦命令里出现 `-f`，compose 就不自动加载 `compose.override.yaml`。

### 3.3 本地开发（直连宿主机 MySQL 的建表）

适合改代码时用（有 `--reload` 热重载）：

```powershell
net start MySQL80                                  # 启动本机 MySQL
Copy-Item .env.example .env                        # 填 DB_HOST=127.0.0.1 / DB_USER=root 等
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

表结构用迁移文件建（不要手写 `CREATE TABLE`）：

```powershell
$env:MYSQL_PWD='你的root密码'
$mysql = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
& $mysql -u root -e "CREATE DATABASE IF NOT EXISTS job_tracker CHARACTER SET utf8mb4;"
foreach ($f in Get-ChildItem migrations\*.sql | Sort-Object Name) {
  cmd /c "`"$mysql`" -u root --default-character-set=utf8mb4 job_tracker < `"$($f.FullName)`""
}
```

> **为什么用迁移文件而不是手写建表**：表结构有 20+ 列、6 次变更历史，手写必然与实际不符（README 之前那版就是典型例子）。迁移文件是 schema 的唯一真相。

### 3.4 手机访问

| 场景 | 做法 |
|---|---|
| 同一 WiFi | 应用容器已映射 `8000`，用 `ipconfig` 查 WLAN 的 IPv4，访问 `http://<IP>:8000/docs` |
| 异地（临时演示） | 内网穿透（如 cpolar），**但务必先确认 `DEBUG=false`、注册已关闭** |

⚠️ `--host 0.0.0.0`（Docker 里已默认）是手机能访问的前提；只绑 `127.0.0.1` 手机一定打不开。

### 3.5 备份与恢复

`compose.yaml` 里有一个 `backup` 服务：**启动时立刻备一份，之后每 24 小时一次，只保留最近 14 天。**

```powershell
docker compose logs backup          # 看每次备份的结果
ls backups\                         # 备份文件在宿主机这个目录里
```

**备份文件**：`backups/job-tracker-YYYY-MM-DD.sql.gz`（几十 KB）。
它由 `mysqldump --single-transaction` 生成——InnoDB 一致性快照，**不锁表、不影响你正在用**。

**为什么要备份**（不是因为重启会丢数据——重启不会）：

| 真实风险 | 说明 |
|---|---|
| **误操作** | 点错删除、写错 `DELETE`、手滑 `docker compose down -v` |
| Docker 环境重置 | `docker system prune -a --volumes`、重置 Docker Desktop、重装 WSL |
| 迁移 | 换电脑 / 搬到云服务器时，数据锁在 `docker_data.vhdx` 里，**没有 dump 就搬不走** |

**恢复**（注意：`/backup` 只挂在 `backup` 容器上，所以要在那个容器里执行）：

```powershell
# 1. 建一个临时库验证（不要直接覆盖正式库！）
docker compose exec db mysql -u root -p你的root密码 -e "CREATE DATABASE restore_check CHARACTER SET utf8mb4;"

# 2. 把备份灌进去
docker compose exec backup sh -c 'gunzip -c /backup/job-tracker-2026-11-24.sql.gz | mysql -h db -u root -p"$MYSQL_ROOT_PASSWORD" restore_check'

# 3. 比对行数，确认无误后再决定是否覆盖正式库
docker compose exec db mysql -u root -p你的root密码 -e "SELECT COUNT(*) FROM restore_check.jobs;"
```

> **原理**：`mysqldump` 默认不带 `CREATE DATABASE`，所以可以灌进任意库名——这就是为什么能先恢复到 `restore_check` 里检查，而不是直接毁掉正式数据。

> **异地备份**：脚本只把备份放在同一块硬盘上。如果整块盘坏掉，备份和原数据一起没。建议每年手动拷一两次到网盘。

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

> ⚠️ **本节是 P0 版本的设计记录，已与当前 schema 不符。**
>
> 当前实际情况：
> - 只有 **`jobs`** 和 **`users`** 两张表（`status_log` **尚未实现**，见 [BACKLOG](docs/BACKLOG.md)）
> - `jobs` 有 22 列（含 AI 分析相关的 `match_score` / `verdict` / `analysis` / `analyzed_at`）
> - 表结构以 **`migrations/*.sql` 为准**，完整 DDL 见 [API.md 附录 A](docs/API.md)
>
> 下面保留 P0 的设计思路（双表拆分"现状 / 历史"）作为演进参考，**不要照它建表**。

```sql
-- P0 设计（已过时，仅作对照）
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