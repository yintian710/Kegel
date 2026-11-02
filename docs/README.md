# Kegel 每日提肛打卡 · 项目文档库

欢迎查阅 **Kegel** 系统的完整技术与业务文档。

Kegel 是一个基于 **LINUX DO Connect** 身份认证的每日提肛自律打卡系统。系统集成了分步计时练习、站内积分激励、积分商城（兑换 LDC 自动发货）与独立 LDC 赞助支持平台。

---

## 📚 文档目录索引

| 文档 | 主要内容 | 目标受众 |
|---|---|---|
| [1. 系统架构与设计 (architecture.md)](./architecture.md) | FastAPI 分层、PostgreSQL 事务、Vue 3 前端与安全机制 | 开发者、架构师 |
| [2. 核心业务流程详解 (features.md)](./features.md) | 三组练习计时、积分额度风控、商品兑换自动发货、赞助榜 | 产品、运营、维护者 |
| [3. API 接口规范大全 (api_reference.md)](./api_reference.md) | 全站 RESTful JSON 接口、请求/响应结构体、错误码 | 前端与后端集成人员 |
| [4. 生产部署与运维指南 (deployment.md)](./deployment.md) | 环境变量配置、Nginx/Caddy 反向代理、安全加固与备份 | 运维人员、站长 |

---

## ⚡ 核心设计亮点

```mermaid
graph TD
  User["LINUX DO 社区用户"] --> Auth["LINUX DO Connect OAuth"]
  Auth --> Session["HttpOnly 签名 Session Cookie"]

  subgraph Client["前端客户端 Vue 3 + Vite"]
    Layout["AppLayout 统一导航与账户区"]
    Home["首页 /<br/>每日正式打卡"]
    PracticePage["练习 /practice<br/>浏览器本地计时"]
    Shop["商店 /shop<br/>积分钱包与商品兑换"]
    Donate["赞助 /donate<br/>LDC 赞助与榜单"]
    Admin["后台 /admin<br/>全站监控与规则管理"]
    Layout --> Home & PracticePage & Shop & Donate & Admin
  end

  subgraph Server["后端 FastAPI + uvicorn"]
    Views["views<br/>路由、参数与鉴权入口"]
    Service["service<br/>业务编排与事务"]
    Common["common<br/>外部接口与支付日志"]
    ORM["infrastructure<br/>Tortoise ORM"]
    Views --> Service
    Service --> Common
    Service --> ORM
  end

  subgraph Storage["数据持久化"]
    DB[("PostgreSQL<br/>事务级咨询锁串行化关键写操作")]
    Log["本机 UTF-8 JSONL<br/>支付对账日志"]
  end

  subgraph External["外部服务"]
    Connect["connect.linux.do<br/>OAuth2 授权登录"]
    CreditDistribute["credit.linux.do/lpay/distribute<br/>商户转账自动发货"]
    CreditPay["credit.linux.do/epay/pay/submit.php<br/>赞助支付与异步回调"]
  end

  Session --> Client
  Client -->|"/api/*"| Views
  ORM --> DB
  Common --> Log
  Common --> Connect & CreditDistribute & CreditPay
```

1. **前后端分离、职责清晰**：
   - 后端使用 FastAPI、Tortoise ORM 与 PostgreSQL，按 `views → service → infrastructure` 分层。
   - 前端使用 Vue 3、TypeScript、Vite、Naive UI 与 Pinia，开发时由 Vite 代理 `/api`。
2. **强一致性事务**：
   - 积分增减、额度占用、限购核算和赞助到账均在 PostgreSQL 事务中完成。
   - 关键写流程使用事务级咨询锁串行化，避免超领、重复入账与负余额。
3. **安全防线闭环**：
   - 会话 Cookie 使用签名并设置 `HttpOnly`、`SameSite=Lax`，生产环境启用 `Secure`。
   - 外部支付使用 MD5 规范签名及异步通知验签；API 使用统一响应信封。
4. **现代响应式体验**：
   - 前端布局组件统一导航、账户状态和登录退出行为。
   - 练习支持淡入淡出、桌面与移动视口，并保留浏览器本地训练进度。
