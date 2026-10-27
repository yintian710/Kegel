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
  - `next`：可选，登录成功后的回跳路径（限 `/`、`/shop`、`/donate`、`/admin`，默认 `/`）。
- **说明**：生成带有随机防伪 `state` 的 HMAC-SHA256 签名 Cookie，并重定向至 `https://connect.linux.do/oauth2/authorize`。
- **进站登录**：配置完整 OAuth 凭据后，未登录访问首页、商店、赞助页、管理页及其 `.html` 地址时直接跳转授权登录；用户数据接口和练习接口返回 `401`，不创建匿名练习记录。图标、支付通知与独立口令接口保持原访问方式。

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
- **认证**：配置完整 OAuth 凭据时必须登录，否则返回 `401`；未配置时保留公开状态查询。
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
- **请求体**：`{}`
- **说明**：记录第 1 组触发打点；返回当前进行中的练习凭证。
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

### 2.4 推进下一组练习
- **路径**：`POST /api/session/step`
- **请求体**：
```json
{ "token": "dGVzdC10b2tlbi0..." }
```
- **说明**：若距离上一组触发时间不足 `min_step_seconds`，将返回 `429` 拒绝推进；超过 10 分钟返回 `409` 重置。

### 2.5 结算三组打卡并锁定名次
- **路径**：`POST /api/session/complete`
- **请求体**：
```json
{ "token": "dGVzdC10b2tlbi0..." }
```
- **说明**：校验第 3 组倒计时结束。在写事务内原子分配当天名次与奖励积分，生成未领取记录。

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
