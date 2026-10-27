# Kegel 每日提肛打卡 · 项目文档库

欢迎查阅 **Kegel** 系统的完整技术与业务文档。

Kegel 是一个基于 **LINUX DO Connect** 身份认证的每日提肛自律打卡系统。系统集成了分步计时练习、站内积分激励、积分商城（兑换 LDC 自动发货）与独立 LDC 赞助支持平台。

---

## 📚 文档目录索引

| 文档 | 主要内容 | 目标受众 |
|---|---|---|
| [1. 系统架构与设计 (architecture.md)](./architecture.md) | 零依赖架构、SQLite WAL 事务设计、状态机与安全机制 | 开发者、架构师 |
| [2. 核心业务流程详解 (features.md)](./features.md) | 三组练习计时、积分额度风控、商品兑换自动发货、赞助榜 | 产品、运营、维护者 |
| [3. API 接口规范大全 (api_reference.md)](./api_reference.md) | 全站 RESTful JSON 接口、请求/响应结构体、错误码 | 前端与后端集成人员 |
| [4. 生产部署与运维指南 (deployment.md)](./deployment.md) | 环境变量配置、Nginx/Caddy 反向代理、安全加固与备份 | 运维人员、站长 |

---

## ⚡ 核心设计亮点

```mermaid
graph TD
  User["LINUX DO 社区用户"] --> Auth["LINUX DO Connect OAuth"]
  Auth --> Session["HMAC-SHA256 无状态 Session Cookie"]
  
  subgraph Client["前端客户端 (Vanilla Modern Web)"]
    Home["首页 /<br/>三组逐次提肛练习"]
    Shop["商店 /shop<br/>积分钱包 & 商品兑换"]
    Donate["赞助 /donate<br/>LDC 赞助 & 实时榜单"]
    Admin["后台 /admin<br/>全站监控 & 规则管理"]
  end

  subgraph Server["后端服务 (Python 3.14 零依赖标准库)"]
    HTTP["ThreadingHTTPServer<br/>队列扩展 (128)"]
    Practice["practice.py<br/>逐组触发校验 & 10分钟超时重置"]
    Credits["credits.py<br/>强事务入账/扣减/退还流水"]
    Catalog["catalog.py<br/>商品管理 & 单人/全站限购校验"]
    Donations["donations.py<br/>MD5 异步通知验签 & 防重放"]
  end

  subgraph Storage["数据持久化 (SQLite WAL Mode)"]
    DB[("checkin.db<br/>排他写事务 BEGIN IMMEDIATE")]
  end

  subgraph External["外部服务 (LINUX DO 生态)"]
    Connect["connect.linux.do<br/>OAuth2 授权登录"]
    CreditDistribute["credit.linux.do/lpay/distribute<br/>商户转账自动发货"]
    CreditPay["credit.linux.do/epay/pay/submit.php<br/>赞助跳转与异步回调"]
  end

  Session --> Client
  Client --> HTTP
  HTTP --> Practice & Credits & Catalog & Donations
  Practice & Credits & Catalog & Donations --> DB
  HTTP --> External
```

1. **绝对零外部依赖**：
   - 依赖项仅为 `Python >= 3.14` 标准库（`dependencies = []`），无需 `pip install`，无包版本冲突或供应链安全漏洞。
2. **纯粹的强一致性事务**：
   - 数据库使用 SQLite 开启 **WAL 模式**（读写不互斥）。
   - 所有写操作（积分增减、额度占用、限购核算、赞助到账）均在 `BEGIN IMMEDIATE` 互斥写事务中执行，杜绝超领与负余额。
3. **安全防线全闭环**：
   - 会话 Cookie 采用 HMAC-SHA256 签名，防御时序攻击（`hmac.compare_digest`），打上 `HttpOnly`、`SameSite=Lax` 与 `Secure` 标记。
   - 外部支付使用 MD5 严格升序排序签名及防伪通知核验。
4. **现代极简设计与响应式体验**：
   - 纯净白底、深灰文字与青绿色点缀，全站无背景图与冗余框框。
   - 三组练习带有平滑淡入淡出动效，倒计时结束暂停等待主动点击，完美适配桌面与手机视口。
