# 项目记忆 · Kegel 每日提肛打卡

本文件是项目级长期记忆，供后续会话快速恢复上下文。修改代码前先读这里与 `README.md`。
详细文档见 `docs/`（注意：`docs/architecture.md`、`docs/deployment.md` 有部分内容已被代码超越，见文末「文档与现状差异」）。

## 一句话概述

基于 **LINUX DO Connect (OAuth)** 的每日提肛打卡站点。后端 Python 3.12 + FastAPI + Tortoise ORM + PostgreSQL；前端 Vue 3 + Vite + TypeScript + Naive UI + Pinia。功能包含：每日三次手动打卡（按名次发站内积分、连续工作日加成）、独立练习/训练榜、积分商店（积分兑换 LDC 自动发货）、独立 LDC 赞助页、人工复核风控、管理后台。

## 快速命令

```bash
# 后端（仓库根目录）
cp .env.example .env            # 填写 PG / OAuth / 密钥 / ADMIN_USER_IDS
uv sync
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/schema.sql   # 手动建表，应用不自动建表
uv run uvicorn app.server:app --host 127.0.0.1 --port 7188

# 前端
cd frontend && pnpm install && pnpm dev     # http://localhost:5173，proxy /api -> 127.0.0.1:7188
pnpm build                                  # base 为 '/'（见 vite.config.ts）

# 测试（pgserver 启动临时 PostgreSQL，无需手建库）
uv run pytest
```

## 技术栈

- 后端：FastAPI + uvicorn（async）、Tortoise ORM(asyncpg)、PostgreSQL only、APScheduler 3.x、httpx(async)、orjson、arrow+tzdata、uv/pyproject。
- 前端：Vue 3 + TS、Vite、Naive UI、Pinia（轻用）、Vue Router 4（History）、axios；unplugin-auto-import / unplugin-vue-components 自动导入，生成 `src/auto-imports.d.ts`、`src/components.d.ts`（需提交）。

## 目录结构

```
app/
  server.py            # FastAPI 实例、lifespan、全局异常→统一信封、context_middleware
  config.py            # Settings 静态类，仅读环境变量，含 .env 极简加载；启动即校验
  views/               # 第一层：HTTP 路由（参数、鉴权调用、good()/bad()），无业务判断
  service/             # 第二层：业务编排 + 事务（不依赖 FastAPI）
  common/              # 第三层：外部 I/O（httpx 客户端、linuxdo、payment_log、scheduler）
  infrastructure/database/  # 第四层：Tortoise Model（schemas/*）+ fetch/execute/write_txn
  utils/               # result(信封/ID归一)、exceptions(APIError)、snowflake、timeutil
  assets/img/          # 站点图标（经 /api/icon 提供）
frontend/src/
  main.ts / App.vue    # NConfigProvider/NMessageProvider/NDialogProvider + AppLayout + RouterView
  router/index.ts      # 5 条路由，afterEach 应用标题/描述偏好
  layouts/AppLayout.vue# SiteNavigation + slot + PreferencesPanel
  pages/               # HomePage/PracticePage/ShopPage/DonatePage/AdminPage
  components/          # SiteNavigation、PreferencesPanel、PracticeSettings、Admin*
  api/http.ts          # 唯一 axios 实例，拦截 code!=0 抛 ApiError
  api/index.ts         # 所有接口函数与 TS 类型，返回 data 字段
  composables/         # useIdentity、useLocalPractice、usePreferences、useBodyAttributes
  stores/identity.ts   # 身份 store（refresh / requireLogin）
  styles/styles.css    # 全局样式
docs/                  # 设计/接口/部署文档（见文末）
sql/schema.sql         # 权威表结构（幂等，可重复执行）
tests/                 # pytest 行为回归测试（conftest.py 提供 client/clock）
scripts/               # deploy.sh / update-backend.sh / update-frontend.sh
```

## 后端分层与关键约定

- 调用方向严格单向：`views → service → infrastructure`；`common` 只被 `service` 调用。
- **统一响应信封**（`app/utils/result.py`）：成功 `{code:0,data:...,msg:"success"}`；失败 `{code:<http status>,data:null,msg}`。所有 `id` / `*_id` 整型在 `normalize()` 中转成字符串（防 JS 精度丢失）。
- **异常映射**：`APIError(message, code)` → 对应状态码；`ValueError`→409；`IntegrityError`→409；`TypeError`/`RequestValidationError`→400；`StarletteHTTPException`→对应码。
- **主键**：Snowflake 64-bit（`SNOWFLAKE_WORKER_ID`，0–1023，生产必须显式设置）。
- **写事务**：`app/infrastructure/database/__init__.py` 的 `write_txn()` 开启事务并取全局咨询锁 `pg_advisory_xact_lock(7188001)`，串行化“先查后写”（名次、余额、限购、幂等）。约定：service 层写函数**要求调用方已开启 `write_txn()`**；读用 `fetch/fetch_one`，简单语句用 `execute`。
- 时间统一按 `Asia/Shanghai`（`timeutil.day_key/clock_hhmm/iso_time`）；存储多用 epoch 秒（float）。
- 配置 `Settings` 为普通类、仅 env；生产校验：`APP_SECRET>=32`、`SNOWFLAKE_WORKER_ID` 必填（非本地时）。

## 数据表（sql/schema.sql 为准）

`checkin_settings`(k/v JSON)、`days`、`visits`、`reviews`、`sessions`（首页打卡会话）、`entries`（打卡名次+奖励，UNIQUE(day,rank)）、`points_wallets`、`points_ledger`（UNIQUE(kind,reference) 幂等）、`practice_triggers`、`training_records`（独立训练，UNIQUE(user_id,round_id)）、`shop_products`、`shop_purchases`（UNIQUE(user_id,request_id)）、`donation_orders`、`donation_settlements`。

注意：`sessions`/`entries`/`reviews` 是复合主键，Tortoise 只能声明单列主键，**禁止对这类 Model 调 `instance.save()`**，一律 `filter(...).update()/create()`。旧的 `practice_completions` 表已废弃删除，被 `training_records` 取代。根目录 `checkin.db` 是旧 SQLite 遗留（已 .gitignore）。

## 核心业务规则

- **每日开放**：`days.opened_at` 为 NULL 即未开放；每日 `deadline`（默认 22:00）到点自动开放，也可 `POST /api/admin/open` 手动或 `POST /api/trigger/open`（X-Trigger-Token）或轮询 `condition_url` 返回 `{"open":true}` 提前开放。`tick()` 由 APScheduler 每 1 秒跑（`server.lifespan` 启动）。
- **首页打卡**（`/`，固定三次手动）：`/api/session/start → /step → /complete`，每次间隔默认 8 秒（`min_step_seconds`）；提前推进/完成返回 429；>10 分钟未继续失效；完成时按名次写 `entries`（第 1–10/11–20/21–50 名默认 1000/500/100 积分，之后无名次奖励）；奖励 `reward_status` 需用户 `POST /api/claim` 主动领取并入钱包（幂等）。
- **连续工作日加成**：首个连续工作日 0%，之后每多一天 +1%，上限 +100%；周末不增天也不中断；小数向下取整。见 `checkin._workday_streak/_apply_streak_bonus`。
- **独立练习**（`/practice`）：浏览器本地计时（`useLocalPractice.ts`），支持手动/自动、1–20 次、每次 2–10 秒，三阶段比例默认 45/40/15（可 0% 取消、可自定义三段文字，最多 24 字）。完成后 `POST /api/practice/records` 上传起止时间(ms)/次数/方式/间隔；服务端校验：开始≤1 小时、结束≤5 分钟、未来≤30 秒、总时长≥次数×间隔、区间不重叠、同 round_id 幂等/改内容拒绝。训练**不影响**打卡、积分、奖励，仅计入独立训练榜（每日榜+总榜，各前 50）。
- **商店/自动发货**（`/shop`）：商品品类仅 `LDC`；兑换在写事务内校验个人/全站限购与当日 LDC 额度、扣积分、存 `pending` 订单并提交，再调 Credit `/lpay/distribute`。返回非空 `data.trade_no` 即成功；明确拒绝→退款(记 `shop_refund`)；超时/结果不明→`uncertain`。`catalog.check_delivery` 按 `out_trade_no` 向 Credit `GET /epay/api.php` 查询（`query_ldc_order`）：`status=1` 且单号/金额一致→`success` 并回填交易号；HTTP 404“订单不存在”且下单满 30 秒→`failed` 并退分（`MISSING_GRACE_SECONDS`）；其余（状态未知、查询出错）保持 `uncertain`、绝不自动退分。APScheduler 每 300 秒跑 `check_all_uncertain`；用户 `POST /api/shop/orders/<order_no>/check`（仅本人订单，同单 10 秒冷却）、管理员 `POST /api/admin/purchases/check` 与 `/<order_no>/check`（无需二级密码）可主动触发；人工对账 `reconcile` 作兜底。`request_id` 幂等。全站每日 LDC 额度由 `DAILY_LDC_LIMIT`（默认 800，0 停兑换，不影响积分）控制，按 `ldc_amount` 精确占用。
- **商品品类与限时折扣**：后台「商店 → 上架商品」可建 `LDC` 商品，或 `TICKET` 抽卡券（`draw_count` 1/10/100，积分购买，不限购、不占 LDC 额度）。每个商品可开「限时折扣」：`promo_enabled` + `promo_bp`（1000–9900，8000=8 折）+ `promo_ends_at`（epoch 秒，须晚于当前；到点自动失效恢复原价；关闭即清空）。价格 `catalog.price_with_discount` 返回 `(原价, 实付, 称号折扣bp, 称号节省, 限时节省)`：先打限时折扣，再叠加用户称号折扣（乘法）；限时折扣的节省存 `shop_purchases.points_promo_saved`，**不计入**称号折扣每日节省上限 `DAILY_DISCOUNT_SAVE_CAP`。`GET /api/shop` 的商品带 `promo_active` 与按当前用户算好的 `price_now`，前端只展示。限时折扣生效时不再使用旧的 `special_discount_bp`（特价，无后台入口）。
- **人工对账**：管理后台对 `uncertain` 订单二选一（已发货 / 未发货退分），需二级密码，每个订单只处理一次。
- **不发货名单**：`checkin_settings.no_payout_user_ids`（纯数字 ID，≤200，管理页配置需二级密码）。名单内用户兑换不调 Credit，订单仍记 `success` 并返回 18 位数字流水号，仅写 `ldc.withheld` 支付日志；管理端订单标红（`no_payout`），商店页面对用户不可见。每日打卡榜中名单用户置灰（`skipped=true`、`rank=null`）且不占名次：`checkin._effective_ranks` 算出不含名单用户的名次，其他人按该名次领奖、发券；名单用户自己的积分奖励仍按原完成序号（`entries.rank`，保持唯一序号）计算，保持不变。榜单项 `position` 为完成先后序号，`completed_at` 为各人真实完成时间。连续打卡榜 `checkin.streak_leaderboard`：按当前连续工作日数排名（今日已打，或上个工作日已打则连续仍有效），名单用户同样置灰不占名次。
- **独立赞助**（`/donate`）：赞助**不增加站内积分**。`POST /api/donations/create` 生成 MD5 签名表单，浏览器直接 POST 到 `credit.linux.do/epay/pay/submit.php`。回调 `GET /api/payments/ldc/notify` 做 MD5 验签+订单/商户/金额/交易号唯一性校验后写 `donation_settlements`；浏览器回跳不确认到账。赞助榜只统计已结算订单。
- **风控/复核**：`record_visit` 记录访问（IP 哈希+匿名 visitor Cookie）；10 分钟 ≥20 次或连续 6 次固定周期→写 `reviews`，待审核用户打卡/训练返回 403，管理员 `POST /api/admin/review` 批准。

## 鉴权与安全

- 会话：`linuxdo_session` Cookie（HMAC-SHA256 签名，HttpOnly/SameSite=Lax，生产 Secure），有效期 5 天并滑动续期；`checkin_visitor` 匿名访客 Cookie；`oauth_state` 一次性 Cookie。`APP_SECRET` 为签名密钥。
- 身份来源：`context_middleware` 从 Cookie 解析 `request.state.user`；`auth.require_user`（401）、`require_admin`（`ADMIN_USER_IDS`，403）、`require_trigger`（X-Trigger-Token）。
- 管理员=登录用户在 `ADMIN_USER_IDS` 内（无独立口令）。敏感操作（改奖励、商品上/下架、人工加积分、不发货名单）需**二级密码**：`ADMIN_SECONDARY_PASSWORD`（明文）或 `ADMIN_POINTS_PASSWORD_HASH`（PBKDF2-HMAC-SHA256, 600000 轮, 16 字节盐，格式为 `<算法标识>$600000$<16字节盐hex>$<64位摘要hex>`）。可用请求体 `secondary_secret` 或头 `X-Secondary-Password`。
- POST 中间件校验 `Origin == APP_BASE_URL`、body ≤ 64KB；响应加 `X-Content-Type-Options/X-Frame-Options/Referrer-Policy/Cache-Control`。
- 支付审计日志：`app/common/payment_log.py` 写 UTF-8 JSONL（默认根目录 `checkin.payments.jsonl`，权限 0600），自动脱敏（Authorization/Cookie/sign/secret/token/二级密码/已配置密钥）。审计路径见 `server.AUDITED_PATHS`。

## API 端点速查（均 `/api` 下，除 health）

- 公开：`GET /health`、`GET /api/heartbeat`、`GET /api/icon?size=`、`GET /api/status`、`GET /api/leaderboard/streak`（连续打卡榜）、`GET /api/practice`、`GET /api/donations`、`GET /api/shop`(配置 OAuth 后需登录)
- 认证：`GET /api/auth/linuxdo/start?next=`、`GET /api/auth/linuxdo/callback`、`GET /api/auth/logout`
- 打卡/练习：`POST /api/visit`、`POST /api/session/start|step|complete`、`POST /api/claim`、`POST /api/practice/records`(须登录)
- 商店/赞助：`POST /api/shop/purchase`、`POST /api/shop/orders/<order_no>/check`、`POST /api/donations/create`、`GET /api/payments/ldc/notify`(纯文本)
- 管理（需管理员 Cookie）：`GET /api/admin`、`GET /api/admin/users?q=`、`POST /api/admin/open|settings|review|points/add|products|products/<id>/archive|purchases/<order_no>/reconcile|purchases/check|purchases/<order_no>/check`
- 外部：`POST /api/trigger/open`

完整请求/响应示例见 `docs/api_reference.md`（与代码基本一致）。

## 前端约定

- `http.ts` 唯一 axios 实例：响应拦截 `code!==0` 抛 `ApiError(msg, code, status)`，页面无需再判；`api/index.ts` 函数返回 `data`。
- 身份：`stores/identity.ts` + `useIdentity`，`requireLogin(path)` 在需要登录且未登录时跳 `loginUrl`。
- 所有页面复用 `AppLayout`（SiteNavigation + slot + PreferencesPanel）；导航项固定「首页/提肛练习/商店/赞助/管理」，按 route 高亮，窄屏横向滚动。
- 称呼偏好：`usePreferences` 的 `ft()` 把「提肛」替换为用户自定义称呼或隐藏；URL `?hide_tigang=1`、`?exercise_name=xxx` 可直接控制；设置存 localStorage。
- 练习本地状态：`useLocalPractice`（localStorage 存 偏好+会话+待上传 pending 队列），断网可练、恢复后重传；`PracticeSettings.vue` 管次数/时长/三阶段比例/阶段文字。
- 长表格统一用 `components/ScrollTable.vue` 包裹（`minRows`/`maxRows`/`rowHeight` 定高，超出在组件内滚动、表头吸顶）；后台表格用 `.adm-tablewrap`（含最小高度）。新增长表格不要让页面无限变长。
- 前台文案、指标、排行榜均在页面内渲染；`AdminPage` 用确认弹窗 + 二级密码执行敏感操作。

## 环境变量（见 .env.example）

`HOST/PORT/APP_BASE_URL/FRONTEND_BASE_PATH/DATABASE_URL/SNOWFLAKE_WORKER_ID/APP_SECRET/ADMIN_USER_IDS/ADMIN_SECONDARY_PASSWORD/ADMIN_POINTS_PASSWORD_HASH/LINUXDO_CLIENT_ID/LINUXDO_CLIENT_SECRET/LINUXDO_REDIRECT_URI/LDC_DONATION_ENABLED/LDC_LIVE/LDC_API_BASE/LDC_CLIENT_ID/LDC_CLIENT_SECRET/DAILY_LDC_LIMIT/PAYMENT_LOG_PATH/CHECKIN_TRIGGER_TOKEN/CHECKIN_CONDITION_TOKEN`。
注意：`LDC_LIVE`（或旧名 `LDC_AUTO_DISPATCH`）控制真实发货，false 为模拟发货。

## 部署

- 单机 uvicorn + 反向代理；`scripts/deploy.sh` 按改动自动重建前端/重启后端（可 `--backend/--frontend/--all`）。`update-backend.sh` 用 PID 文件管理进程；`update-frontend.sh` 需 `DEPLOY_DIR`。
- 前端生产 `base:'/'`（不是 `/new/`）；History 路由需回退 `index.html`。
- 生产必须 HTTPS、显式 `SNOWFLAKE_WORKER_ID`、≥32 字符 `APP_SECRET`；多实例 worker id 不同，调度任务需避免重复。
- 支付日志是各实例本机文件，多实例需分别采集。

## 测试

`tests/conftest.py` 用 `pgserver` 起临时 PG、`execute_script(schema.sql)` 建表，提供 `client`（带 `request(path, body, user=, admin=, headers=, raw=)`）与可拨动的 `clock`（替换 `timeutil.now`）。覆盖：打卡/管理/触发鉴权、信封与字符串 ID、训练上传与榜单、商店/发货幂等与限额、赞助验签与日志脱敏。新增功能务必补 `tests/test_*.py`。

## 文档与现状差异（重要）

- `docs/architecture.md` 部分过时：不要再以其中的 `SSO_AUTH_ENABLED/LOCAL_USER_ID/SUPER_ADMINS/argon2` 为准——实际仅用 LINUX DO OAuth + `ADMIN_USER_IDS`。
- `docs/deployment.md` 仍写前端挂 `/new/` 与 `FRONTEND_BASE_PATH=/new/`；实际已改为根路径 `/`（commit「构建基路径改为 /」）。以 `frontend/vite.config.ts` 与 `.env.example` 为准。
- `docs/title_gacha.md`、`docs/title_pool*.csv/md`、`docs/title_scarcity.md` 是**称号抽卡系统设计稿，尚未实现**（代码中无 gacha/称号相关实现）。
- `docs/task.md`、`docs/fu` 是历史需求/改进备注（部分已实现，如取消强制登录、隐藏「提肛」、淡入淡出、自主练习、提醒、管理员按人识别）。
- `README.md` 是当前面向用户的功能说明，最可信；`docs/api_reference.md` 与代码一致度高。

## 已知注意事项

- 写业务函数前确认是否已在 `write_txn()` 上下文中（credits/catalog/checkin/practice 写函数依赖它）。
- 幂等键：打卡领取 `reference=f"{day}:{user_id}"`；商店 `request_id`；加积分 `request_id`；训练 `round_id`；赞助 `out_trade_no`/`trade_no`。
- 金额/积分校验：积分 0–100000000 整数；LDC 0.01–10000.00（两位小数，字符串存储）；单笔赞助上限 10000.00。
- 时间陷阱：`training_records` 用毫秒时间戳，`visits/entries/sessions` 等用 epoch 秒；前端本地训练用 `crypto.randomUUID()` 作 round_id/token。
- 不要提交 `.env`、真实密钥、`checkin.payments.jsonl`、`*.db`。
