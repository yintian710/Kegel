# 生产部署与运维指南

本文档提供 **Kegel** 系统的生产环境部署规范、反向代理配置、安全加固及数据备份方案。

---

## 1. 运行环境要求

- **操作系统**：Linux (Ubuntu 22.04 / Debian 12 / AlmaLinux 9 等推荐) / macOS
- **Python 环境**：`Python >= 3.14`（推荐使用 `uv` 管理）
- **外网条件**：
  - 需要能够正常出网访问 `connect.linux.do` 和 `credit.linux.do`
  - 生产环境必须拥有已解析的域名并配置 **HTTPS 证书**

---

## 2. 环境变量配置清单 (`.env`)

在项目根目录下复制 `.env.example` 为 `.env` 并按需配置：

```bash
# 1. 存储与网络
CHECKIN_DB=checkin.db
HOST=127.0.0.1
PORT=8000
APP_BASE_URL=https://kegel.yourdomain.com

# 2. 安全与密钥 (生产环境必须设置至少 32 字符的强随机串)
APP_SECRET=your-super-long-and-secure-random-secret-key-at-least-32-chars
ADMIN_TOKEN=your-strong-admin-token-for-management-console
# 管理员加积分二级密码，仅填写下方生成命令输出的加盐哈希；留空禁用加积分:
ADMIN_POINTS_PASSWORD_HASH=

# 3. LINUX DO Connect 授权配置 (用于用户登录)
LINUXDO_CLIENT_ID=your-connect-client-id
LINUXDO_CLIENT_SECRET=your-connect-client-secret
LINUXDO_REDIRECT_URI=https://kegel.yourdomain.com/auth/linuxdo/callback

# 4. LINUX DO Credit 平台商户配置 (用于商品自动发货与独立赞助)
# 开启赞助功能:
LDC_DONATION_ENABLED=true
# 开启商品兑换真实发货 (设为 false 时为模拟发货):
LDC_LIVE=true
LDC_API_BASE=https://credit.linux.do
LDC_CLIENT_ID=your-credit-merchant-id
LDC_CLIENT_SECRET=your-credit-merchant-secret
# 全站每日 LDC 兑换额度（整数 LDC，默认 800；0 停止兑换且不影响签到积分）:
DAILY_LDC_LIMIT=800


# 5. 自动化与调度
CHECKIN_TRIGGER_TOKEN=your-optional-token-to-open-checkin-via-webhook
CHECKIN_CONDITION_TOKEN=your-optional-bearer-token-for-condition-polling
```

修改 `DAILY_LDC_LIMIT` 后必须重启服务才能生效；额度按北京时间每日重置。

---

## 3. 生产反向代理配置

**必须在前端挂一层反向代理（推荐 Caddy 或 Nginx）**，由其负责 TLS 证书续签、慢速连接拦截以及静态资源加速。

### 3.1 Caddyfile 配置示例（最推荐，全自动申请证书）
```caddy
kegel.yourdomain.com {
    encode gzip zstd
    
    # 限制单次请求体体积，防御大包攻击
    request_body {
        max_size 1MB
    }

    reverse_proxy 127.0.0.1:8000 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
```

### 3.2 Nginx 配置示例
```nginx
server {
    listen 80;
    server_name kegel.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name kegel.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/kegel.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kegel.yourdomain.com/privkey.pem;

    client_max_body_size 1M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 保持连接与超时设置
        proxy_connect_timeout 15s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }
}
```

---

## 4. Systemd 守护进程服务配置

在 `/etc/systemd/system/kegel.service` 创建服务文件：

```ini
[Unit]
Description=Kegel Daily Checkin and Shop Service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/Kegel
EnvironmentFile=/var/www/Kegel/.env
ExecStart=/usr/local/bin/python3 app.py
Restart=always
RestartSec=5

# 资源防护限制
LimitNOFILE=65535
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

启动与自启：
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kegel
sudo systemctl status kegel
```

---

## 5. 数据备份与维护策略

系统所有状态和账本流水均持久化在单个 SQLite 文件中（默认 `checkin.db`）。

### 5.1 热备份脚本 (基于 SQLite 官方安全热备)
在 SQLite 运行期间，切勿直接 `cp` 正在处于 WAL 写入的 `.db` 文件。建议使用内置命令执行原子热备份：

```bash
# 运行原子安全热备到指定目录
sqlite3 checkin.db "VACUUM INTO '/backup/kegel_backup_$(date +%Y%m%d_%H%M%S).db';"
```
可将该命令写入每日凌晨定时任务（crontab）：
```bash
0 3 * * * sqlite3 /var/www/Kegel/checkin.db "VACUUM INTO '/backup/kegel_$(date +\%Y\%m\%d).db';"
```

### 5.2 数据库完整性自检
```bash
sqlite3 checkin.db "PRAGMA integrity_check;"
```
输出 `ok` 即表示数据完整无损。

### 5.3 支付请求与响应日志

默认启用，UTF-8 JSONL 格式，追加写入数据库同目录下的 `<数据库名>.payments.jsonl`（默认 `checkin.payments.jsonl`）。设置 `PAYMENT_LOG_PATH=/var/log/kegel/payments.jsonl` 可覆盖位置；服务账户需要目录写入权限，新建文件权限为 `0600`。修改环境变量后重启服务生效。

- 记录 `/api/shop`、`/api/shop/purchase`、`/api/donations`、`/api/donations/create`、`/payments/ldc/notify` 和 `/api/admin/points/add` 的请求 URL、请求头、已接收的请求体及响应头、响应体。管理员加积分的二级密码始终脱敏。
- 记录服务端访问 `/lpay/`、`/epay/` 接口时的请求、完整响应、HTTP 状态及异常。包括非 JSON 和非 2xx 响应，不对业务内容做长度截断。
- 使用 `exchange_id` 关联同一次请求与响应，订单号和交易号用于跨请求对账。回调通过记录 `callback.accepted`（包括已结算订单的重复通知），拒绝记录 `callback.rejected` 及具体原因，处理异常记录 `callback.error`。
- 认证头、Cookie、商户密钥、令牌和签名脱敏；订单号、交易号、金额、错误消息及其他业务字段保留。现有 HTTP 访问日志中的签名也会脱敏。
- 日志独立于数据库事务保存，订单事务回滚不删除日志。文件写入失败时，将脱敏后的完整事件输出到标准错误，不改变支付结果；需同时保留服务的标准错误日志。
- 不自动轮转、截断或删除，备份时需单独保存，持续监控磁盘空间。拒绝超大请求或来源校验失败时，不会为日志额外读取未接收的请求体。

赞助支付通过浏览器表单直接提交至 LDC，服务端仅能记录生成的支付表单和后续回调，无法看到浏览器与网关之间的响应。当前没有主动查单流程。浏览器回跳不会确认到账；回调仍须通过签名、`TRADE_SUCCESS`、商户、订单、金额及交易号校验，不依赖 `code`。未知字段或状态会被拒绝并记录原因，不会因仅有交易号就跳过验签。

日志只覆盖更新并重启后的请求，不能恢复历史未记录的响应。历史可疑失败订单仍需按商户订单号与 LDC 对账。

### 5.4 管理员加积分二级密码

管理员页面的“记录查询 → 用户积分余额”支持搜索用户并增加积分，每笔操作同时需要管理员口令和二级密码。`.env` 中只保存 `ADMIN_POINTS_PASSWORD_HASH`，不保存明文密码。使用 Python 标准库 PBKDF2-HMAC-SHA256，迭代 600000 次、随机 16 字节盐；与普通 SHA-256 摘要不兼容。

在自己的终端运行以下命令，输入两次二级密码（输入不回显）。将输出的整行原样放入 `.env`，然后重启服务：

```bash
python3 -c '
import getpass, hashlib, secrets
value = getpass.getpass("二级密码：")
confirmation = getpass.getpass("再次输入：")
if not value or len(value) > 1024 or value != confirmation:
    raise SystemExit("密码为空、超过 1024 字符或两次输入不一致")
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, 600000).hex()
print("ADMIN_POINTS_PASSWORD_HASH=pbkdf2_sha256$600000$" + salt.hex() + "$" + digest)
'
```

通过系统环境变量或 shell 设置时，须用单引号包住哈希，防止 `$` 被 shell 展开。配置缺失或格式错误时加积分接口拒绝操作；其他管理功能不受影响。每次加积分都需重新输入密码，浏览器不会保存二级密码，支付日志中也会脱敏。

单笔支持 1–100000000 整数积分，余额与 `admin_credit` 流水一起提交。核对目标用户名、ID 和金额后再提交；同一请求重试不会重复加分。加积分不直接调整 LDC 兑换额度，也不确认赞助到账。
