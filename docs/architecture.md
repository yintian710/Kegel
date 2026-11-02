# 技术架构设计文档

> 本文档描述项目的通用技术架构与工程约定，不涉及具体业务逻辑或数据库表结构。

## 一、整体架构

前后端分离，单体部署。无微服务，无消息队列，无缓存中间件。

```
┌─────────────┐     HTTP/JSON      ┌──────────────────────────────┐
│  Vue 3 SPA  │ ◄────────────────► │  FastAPI (uvicorn)            │
│  (Vite)     │   /api/*           │  port 7188                   │
└─────────────┘                    └──────────────┬───────────────┘
                                                  │ asyncpg
                                           ┌──────▼──────┐
                                           │ PostgreSQL   │
                                           └─────────────┘
```

运行时依赖：Python 3.12+、PostgreSQL。前端构建产物静态托管，开发时 Vite proxy 透传 `/api`。

---

## 二、后端分层

```
app/
├── server.py          # 入口：FastAPI 实例、lifespan、全局中间件
├── config.py          # 配置：Settings 静态类，env-only
├── views/             # 第一层：HTTP 路由
├── service/           # 第二层：业务编排
├── common/            # 第三层：外部集成
├── infrastructure/
│   └── database/      # 第四层：ORM 模型
└── utils/             # 工具：响应包装、异常
```

调用方向严格单向：`views → service → infrastructure`，`common` 只被 `service` 调用，跨层禁止跳跃。

### views 层
- 职责：解析参数、鉴权调用、序列化响应，**不含业务判断**。
- 每个模块暴露一个 `APIRouter`，统一在 `views/__init__.py` 聚合，`server.py` 遍历挂载。
- 返回值全用 `good()` / `bad()` 包装。

### service 层
- 职责：事务、规则、多表编排。
- 不依赖 FastAPI（无 `Request`、无 `Depends`），可单独测试。
- 鉴权逻辑（`require_identity`）也在 service 层，views 调用后传入业务函数。

### common 层
- 第三方 API 客户端（封装 httpx 调用）、APScheduler 实例集中在此。
- 不含业务逻辑，只做 I/O 封装。

### infrastructure 层
- Tortoise ORM Model 定义，**不自动建表**（`DB_AUTO_CREATE = False`）。
- 表结构由手写 SQL 文件交付，保留 PostgreSQL 原生特性（CHECK、生成列、部分索引）。
- 所有 Model 从 `infrastructure/database/schemas/__init__.py` 统一导出，其余模块只从这里 import。

---

## 三、关键约定

### 主键
Snowflake ID，64-bit 整数，`SNOWFLAKE_WORKER_ID` 环境变量注入（0–1023）。  
响应时 `result.py` 的 `normalize()` 自动将所有 `id` / `*_id` 字段转 string，防 JS Number 精度丢失。

### 统一响应信封
```python
# 成功
{"code": 0, "data": ..., "msg": "success"}

# 失败
{"code": <int>, "data": null, "msg": "<reason>"}
```
`ValueError` → 409，`IntegrityError` → 409，其余由 views 层手动 `bad()`。

### 配置
`Settings` 是一个普通 Python 类，`class`-level 属性，启动时全部校验，非法配置直接 `raise`。  
不用 Pydantic Settings，不用 yaml，只读环境变量。

### 鉴权
`server.py` 的 HTTP middleware 全局拦截，白名单路径（`/health`、`/api/heartbeat`）直通。  
双模式：`SSO_AUTH_ENABLED=true` 时走 SSO token 换用户；否则用 `LOCAL_USER_ID` 做本地单用户。  
`SUPER_ADMINS`（环境变量逗号分隔 UID）每次解析身份时自动提权，无需改表，不自动降级。

### 定时任务
APScheduler，在 FastAPI `lifespan` 的 startup 阶段启动，shutdown 阶段 `scheduler.shutdown(wait=False)`。调度逻辑在 `service/` 层，`common/scheduler.py` 只负责 setup/teardown。

---

## 四、前端分层

```
src/
├── main.ts            # 挂载：app + router + pinia
├── router/            # 路由表，afterEach 改 document.title
├── layouts/           # 壳：侧边栏 + 顶栏，插槽承载页面
├── pages/             # 页面级组件（重逻辑、本地状态）
├── components/        # 跨页面复用组件
├── api/
│   ├── http.ts        # axios 实例，统一拦截 code≠0 抛错
│   └── index.ts       # 所有接口函数，按业务分组
├── composables/       # 组合式函数（如 useIdentity）
└── stores/            # Pinia（轻用，页面内状态不抽 store）
```

### 接口层约定
`http.ts` 创建唯一 axios 实例，响应拦截器判断 `code !== 0` 时统一 `throw`，页面不需要重复判断。  
`api/index.ts` 所有函数返回 `data` 字段内容，不返回原始信封。

### 自动导入
`unplugin-auto-import`：`vue` / `vue-router` / `pinia` API 无需手动 import。  
`unplugin-vue-components` + `NaiveUiResolver`：Naive UI 组件按需自动注册。  
两个插件均生成 `.d.ts` 提供类型，已纳入 `src/` 追踪。

---

## 五、技术栈汇总

| 关注点 | 选型 | 备注 |
|---|---|---|
| 后端框架 | FastAPI + uvicorn | async-first |
| ORM | Tortoise ORM | asyncpg 驱动 |
| 数据库 | PostgreSQL only | 无 Redis/MySQL |
| 任务调度 | APScheduler 3.x | lifespan 管理 |
| HTTP 客户端 | httpx（async） | requests 仅遗留 |
| 密码 | argon2-cffi | |
| 时间 | arrow + tzdata | 存储 UTC |
| 序列化 | orjson | 替换标准 json |
| 包管理 | uv + pyproject.toml | lockfile 锁定 |
| 前端框架 | Vue 3 + TypeScript | Composition API |
| 构建 | Vite 8 | dev proxy 内置 |
| UI | Naive UI | |
| 状态 | Pinia（轻用） | |
| 路由 | Vue Router 4 | History 模式 |
| HTTP | axios | 统一实例 |
| 包管理 | pnpm | frozen-lockfile |

---

## 六、部署约定

- 生产 `base: '/new/'`，开发 `base: '/'`（vite.config.ts `mode` 判断）。
- 前端构建产物由 `update-frontend.sh` 推送，后端由 `update-backend.sh` 重启 uvicorn。
- 无容器编排要求，单机直接跑 uvicorn 进程即可。
- 生产实例必须显式设置 `SNOWFLAKE_WORKER_ID`，否则启动报错。
