# API 接口规范大全

业务接口默认采用标准 HTTP/JSON 通信，请求体格式为 `application/json`，响应体统一采用（图标接口成功时直接返回 PNG 图片）：
```json
{ "ok": true, ... }
```
异常情况下返回对应的 HTTP 状态码并附带错误提示：
```json
{ "ok": false, "error": "错误原因说明" }
```

---
## 公开图标接口

- **路径**：`GET /api/icon`
- **认证**：无需登录。
- **查询参数**：`size` 可选，支持 `16`、`32`、`48`、`64`、`128`、`180`、`192`、`256`、`512`、`1024`，单位为像素，图片宽高相同。不传时返回原图（1254 × 1254）。
- **响应**：成功返回 `200`，内容类型为 `image/png`，响应体为图片文件；不支持、空值或重复的 `size` 返回 `400` 和 JSON 错误信息。
- **示例**：`/api/icon?size=192` 可直接用作 `<img src="/api/icon?size=192" alt="图标">` 的图片地址。
- **图片文件**：原图位于 `static/img/icon.png`，各尺寸位于 `static/img/icon-{size}.png`，也可通过 `/img/icon-{size}.png` 直接访问。

---


## 1. 身份认证与会话相关

### 1.1 发起 LINUX DO OAuth 登录
- **路径**：`GET /auth/linuxdo/start`
- **查询参数**：
  - `next`：可选，登录成功后的回跳路径（限 `/`、`/practice`、`/shop`、`/donate`、`/admin`，默认 `/`）。
- **说明**：生成带有随机防伪 `state` 的 HMAC-SHA256 签名 Cookie，并重定向至 `https://connect.linux.do/oauth2/authorize`。
- **进站登录**：首页、练习页 `/practice`（含 `/practice.html`）、公开状态、访问打点及练习接口允许访客使用；商店、赞助页、管理页在配置 OAuth 后要求登录，相关用户数据接口返回 `401`。访客不能正式打卡或领取积分。

### 1.2 OAuth 回调处理
- **路径**：`GET /auth/linuxdo/callback`
- **查询参数**：`code` (授权码)、`state` (防伪串)。
- **说明**：向 Connect 平台换取 Access Token，拉取用户唯一数字 ID 和用户名，签发有效期 5 天（`432000` 秒）的 `linuxdo_session` Cookie。有效期内访问已认证页面或业务接口时，签名过期时间与 Cookie 的有效期一同续至访问后的 5 天；过期后须重新登录，退出时清除 Cookie。

### 1.3 退出登录
- **路径**：`GET /auth/logout`
- **说明**：清除会话 Cookie 并重定向至首页。

### 1.4 查询当前登录身份
- **路径**：`GET /api/me`
- **响应示例**：
```json
{
  "ok": true,
  "user": {
    "id": "12345",
    "username": "example_user",
    "name": "昵称"
  }
}
```

---

## 2. 每日打卡与练习接口

### 2.1 查询当日打卡状态与公开榜单
- **路径**：`GET /api/status`
- **认证**：无需登录；访客返回 `user: null`。`leaderboard` 仅展示每日打卡奖励名次，不返回训练榜数据；训练榜统一由 `/api/practice` 提供。
- **响应示例**：
```json
{
  "ok": true,
  "user": { "id": "123", "username": "alice" },
  "day": "2026-10-27",
  "is_open": true,
  "opened_at": "2026-10-27T08:00:00+08:00",
  "open_reason": "manual",
  "deadline": "22:00",
  "timezone": "Asia/Shanghai",
  "min_step_seconds": 8,
  "reward_tiers": [
    { "through": 10, "amount": 1000 },
    { "through": 20, "amount": 500 },
    { "through": 50, "amount": 100 }
  ],
  "wallet": { "balance": 1500 },
  "quota": { "limit": "800.00", "used": "500.00", "remaining": "300.00" },
  "oauth_ready": true,
  "total": 12,
  "entry": {
    "day": "2026-10-27",
    "user_id": "123",
    "username": "alice",
    "rank": 2,
    "amount": 500,
    "reward_status": "unclaimed",
    "completed_at": "2026-10-27T08:05:00+08:00",
    "claimed_at": null
  },
  "session": null,
  "review": null,
  "leaderboard": [
    { "rank": 1, "username": "bob", "amount": 1000, "reward_status": "credited" },
    { "rank": 2, "username": "alice", "amount": 500, "reward_status": "unclaimed" }
  ]
}
```

### 2.2 页面载入访问打点
- **路径**：`POST /api/visit`
- **请求体**：`{}`
- **说明**：仅在用户每次进入页面时调用一次（状态轮询不调用）。用于记录访问频次并检测定时自动化作弊。

### 2.3 开始/恢复当前打卡会话
- **路径**：`POST /api/session/start`
- **请求体**：默认 `{}` 使用手动模式、三次和后台配置的间隔；自动模式使用 `{"mode":"auto","repetitions":20,"interval_seconds":2}`，次数必须为 1–20 整数，间隔必须为 2–5 整数秒。
- **说明**：记录第一次触发，返回有效会话；已完成会话再次启动时创建新轮，不覆盖原有每日奖励凭证。配置与现有进度的方式或次数不同时，创建符合请求配置的新轮。浏览器独立训练页不调用此接口。
- **响应示例**：
```json
{
  "ok": true,
  "session": {
    "token": "dGVzdC10b2tlbi0...",
    "step": 0,
    "eligible": true,
    "wait_seconds": 8,
    "expires_in": 600
  }
}
```

### 2.4 推进下一次练习
- **路径**：`POST /api/session/step`
- **请求体**：
```json
{ "token": "dGVzdC10b2tlbi0..." }
```
- **说明**：距离上次触发不足本轮间隔时返回 `429`；超过 10 分钟返回 `409`。浏览器独立训练页不调用此接口。

### 2.5 结算本轮练习并锁定打卡名次
- **路径**：`POST /api/session/complete`
- **请求体**：
```json
{ "token": "dGVzdC10b2tlbi0..." }
```
- **说明**：校验本轮全部次数及最后一次倒计时。符合开放及审核条件的登录用户获得当天唯一打卡名次及奖励，服务端完成记录保持原有累计规则。浏览器独立训练不调用此接口，不生成正式打卡记录或奖励。

`/practice` 在浏览器本地计时，训练过程中不调用 `/api/session/*`、`/api/visit` 或 `/api/status`。完成后使用独立的训练记录接口上传，不生成正式打卡或奖励。

#### 独立训练记录

- `GET /api/practice`：公开读取训练页面数据，返回 `{ok,user,oauth_ready,day,leaderboard,total_leaderboard,records}`。`leaderboard` 是当日有效独立训练次数榜，`total_leaderboard` 是跨所有日期累计的总榜，两者均包含 `rank,username,count`，各限前 50 名，并统一排除待审核日期的记录；同分按最早上传时间、用户 ID 排序。`records` 仅包含当前登录账号最近 50 轮记录，访客为空。上传接口同样返回每日榜和总榜，重复提交不重复计入任一榜单。
- `POST /api/practice/records`：须登录，请求体示例为 `{"round_id":"12891f40-4e3f-4a38-8c3d-bc1f4a850bb2","started_at":1790000000000,"ended_at":1790000030000,"repetitions":10,"interval_seconds":3,"mode":"auto","expected_user_id":"123"}`。实际起止时间须满足下述时效范围，两个时间为 Unix 毫秒整数；方式为 `manual` 或 `auto`，实际完成次数 1–20 整数、每次时长 `interval_seconds` 为 2–10 整数秒。放弃本轮时仅提交完整完成的次数，零次不提交；三阶段比例由浏览器保存，不参与服务端计数。响应包含与 GET 相同的数据及本次 `record`。
- 记录归属取服务端登录身份；可选 `expected_user_id` 仅校验账号是否切换，不用于指定归属。身份不匹配或同一轮内容冲突返回 `409`，未登录返回 `401`，待审核用户返回 `403`。
- 时间须满足开始早于结束、总时长至少为次数乘间隔；开始不早于当前一小时、结束不早于当前五分钟，最多允许未来 30 秒。非法输入返回 `400`。同用户的时间区间跨日也不得重叠，端点相接允许，重叠返回 `409`。
- 同用户同 `round_id` 的相同内容原样重传幂等成功，即使原时间窗口已经过期也不会重复累计；同编号修改内容返回 `409`。每条记录保存用户、起止时间、次数、方式、间隔、服务端接收日期和接收时间；每日训练榜按接收日期统计。不同用户独立校验。

### 2.6 确认领取站内积分
- **路径**：`POST /api/claim`
- **请求体**：`{}`
- **说明**：将已锁定的签到奖励积分入账至个人钱包，记录流水并更新为 `credited`，支持幂等重复调用。签到积分领取不受每日 LDC 兑换额度限制。

### 2.7 外部触发开启当天打卡
- **路径**：`POST /api/trigger/open`
- **请求头**：`X-Trigger-Token: <CHECKIN_TRIGGER_TOKEN>`
- **请求体**：`{}`
- **说明**：用于外部定时任务或 Webhook 提前开放当天打卡。

---

## 3. 商店与积分兑换接口

### 3.1 获取商店数据（钱包、流水与商品展示）
- **路径**：`GET /api/shop`
- **认证**：可选
- **响应示例**：
```json
{
  "ok": true,
  "user": { "id": "123", "username": "alice" },
  "wallet": { "balance": 1500 },
  "quota": { "limit": "800.00", "used": "500.00", "remaining": "300.00" },
  "ledger": [
    {
      "id": 1,
      "kind": "checkin",
      "reference": "2026-10-27:123",
      "delta": 500,
      "balance_after": 1500,
      "created_at": "2026-10-27T08:06:00+08:00"
    }
  ],
  "products": [
    {
      "id": 1,
      "category": "LDC",
      "name": "1.00 LDC 积分兑换",
      "description": "购买后系统自动调用接口发货",
      "points_price": 500,
      "ldc_amount": "1.00",
      "user_daily_limit": 1,
      "total_daily_limit": 10,
      "user_today_count": 0,
      "user_remaining": 1,
      "total_today_count": 2,
      "total_remaining": 8,
      "is_active": true
    }
  ],
  "purchases": []
}

```

`quota.limit`、`quota.used`、`quota.remaining` 均为两位小数字符串，单位为 LDC；额度按北京时间每日重置。

### 3.2 积分兑换并自动发货
- **路径**：`POST /api/shop/purchase`
- **认证**：必须登录
- **请求体**：
```json
{ "product_id": 1, "request_id": "63097d87-712c-4b44-bf90-58b2b9264461" }
```
- **说明**：
  - 在写事务内检查个人、商品全站限购及当日剩余 LDC 额度，扣除积分并保存 `pending` 订单；提交保存后再发货；
  - `pending`、`success`、`simulated`、`uncertain` 订单占用限购份数与 LDC 额度，`failed` 订单释放额度；
  - `request_id` 可选，须为 16–128 位英文字母、数字、下划线或连字符；商店页面自动生成并在结果不明时保留。相同用户、相同请求编号返回原订单，不再扣分或发货；用于其他商品时拒绝请求。省略编号表示发起新的独立兑换；
  - 调用 `/lpay/distribute` 时使用已保存的订单号作为 `out_trade_no`；非空 `data.trade_no` 即确认成功，不要求 `code == 1`；
  - 缺少交易号时读取 `error_msg`、`message`、`msg` 判断明确拒绝并退款；成功标志但缺交易号、超时或结果不明记为 `uncertain`，进程中断可能保留 `pending`，均需对账且不自动重发；
  - 历史 `failed` 订单可能已经到账，须按商户订单号核对 LDC 记录；本修复不会自动重发、扣回已退款积分或修改历史订单。
- **响应示例**：
```json
{
  "ok": true,
  "status": "success",
  "trade_no": "TX20261027001",
  "error": "",
  "order": {
    "order_no": "SO-20261027-1A2B3C",
    "product_name": "1.00 LDC 积分兑换",
    "points_cost": 500,
    "ldc_amount": "1.00",
    "status": "success"
  }
}
```

---

## 4. 独立赞助接口

### 4.1 获取赞助榜与个人订单
- **路径**：`GET /api/donations`
- **响应示例**：
```json
{
  "ok": true,
  "donation_ready": true,
  "donation_leaderboard": [
    { "rank": 1, "username": "bob", "amount": "50.00", "count": 2 },
    { "rank": 2, "username": "alice", "amount": "10.00", "count": 1 }
  ],
  "donation_orders": [
    {
      "order_no": "LDC3f918e...",
      "amount": "10.00",
      "status": "paid",
      "created_at": "2026-10-27T08:10:00Z",
      "paid_at": "2026-10-27T08:10:30Z"
    }
  ]
}
```

### 4.2 创建赞助支付订单
- **路径**：`POST /api/donations/create`
- **认证**：必须登录
- **请求体**：
```json
{ "amount": "10.00" }
```
- **说明**：返回带有 MD5 防伪签名的表单字段，前端创建隐藏 Form 表单直接 POST 跳转至官方支付平台。

### 4.3 官方支付平台异步通知
- **路径**：`GET /payments/ldc/notify`
- **说明**：官方支付成功回调，校验 MD5 签名、交易单号唯一性并结算订单，成功返回 `success`。

---

## 5. 管理后台接口

全部管理接口均需要请求头：
```http
X-Admin-Token: <ADMIN_TOKEN>
```

| 接口 | 方法 | 请求体说明 | 功能 |
|---|---|---|---|
| `/api/admin` | GET | 无 | 获取系统状态、规则参数、商品列表、发货流水、触发日志及用户余额 |
| `/api/admin/open` | POST | `{}` | 立即手动开启当天的正常打卡 |
| `/api/admin/settings` | POST | `{ "deadline": "22:00", "min_step_seconds": 8, "condition_url": "..." }` | 保存每日基础规则；LDC 兑换额度仅由 `DAILY_LDC_LIMIT` 环境变量配置，修改后需重启 |
| `/api/admin/settings` | POST | `{ "reward_tiers": [{ "through": 10, "amount": 1000 }, ...] }` | 保存阶梯排名奖励配置 |
| `/api/admin/review` | POST | `{ "user_id": "123", "approved": true }` | 批准异常访问标记，恢复正常打卡资格 |
| `/api/admin/products` | POST | `{ "id"?: 1, "category": "LDC", "name": "...", "points_price": 500, "ldc_amount": "1.00", "user_daily_limit": 1, "total_daily_limit": 10, "is_active": true }` | 新增或编辑商品 |
| `/api/admin/products/<id>/archive` | POST | `{}` | 立即下架指定商品 |
| `/api/admin/users?q=<用户名或用户ID>` | GET | 无 | 搜索已有站内记录的数字 ID 用户，用户名不区分 ASCII 大小写、支持部分匹配与 `@` 前缀，ID 精确匹配；最多返回 50 位用户及余额 |
| `/api/admin/points/add` | POST | `{ "user_id": "123", "amount": 250, "secondary_secret": "输入的二级密码", "request_id": "客户端生成的UUID" }` | 验证管理员口令与二级密码后增加站内积分，返回 `user`、`wallet`、`entry` |

基础参数保存只提交 `deadline`、`min_step_seconds` 和 `condition_url`，验证管理员口令即可，不要求二级密码。修改 `reward_tiers` 仍须验证二级密码；基础参数表单不得附带未修改的奖励配置。

加积分说明：

- `ADMIN_POINTS_PASSWORD_HASH` 存储 PBKDF2-HMAC-SHA256 加盐哈希，格式及生成命令见部署文档。未配置或格式错误返回 `503`；二级密码错误返回 `403`，不会清除前端管理员登录状态。管理员口令错误仍返回 `401`。
- `amount` 为 1–100000000 的整数或十进制整数字符串；用户必须存在于站内记录，匿名访客不接受加分。余额不能超过 `9000000000000000`。
- `request_id` 为 16–128 位英文字母、数字、下划线或连字符；相同编号和相同用户、积分重复请求返回原流水；编号已用于其他用户或金额时拒绝，不重复入账。请求重试仍须验证二级密码。
- 余额变动与 `kind=admin_credit` 流水在同一写事务提交；流水失败全部回滚。该接口也写入支付日志，二级密码和哈希不会写入日志或返回前端。
- 搜索覆盖钱包、访问、打卡和赞助记录；今后 OAuth 登录会建立零余额钱包并更新用户名。仅有历史 Cookie、从未在服务端留下用户记录的身份，需再次登录后才能搜索。

