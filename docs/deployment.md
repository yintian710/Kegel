# 生产部署与运维指南

本文档提供 **Kegel** 系统的生产环境部署规范、反向代理配置、安全加固及数据备份方案。

---

## 1. 运行环境要求

- **操作系统**：Linux（Ubuntu 22.04、Debian 12、AlmaLinux 9 等）或 macOS。
- **后端**：Python >= 3.12、`uv`、PostgreSQL。
- **前端**：Node.js 与 `pnpm`，生产构建产物由 Web 服务器静态托管。
- **外网条件**：可访问 `connect.linux.do` 和 `credit.linux.do`；生产域名必须配置 HTTPS。

先同步 Python 依赖：

```bash
uv sync
```

## 2. 环境变量配置清单（`.env`）

复制 `.env.example` 为 `.env`。已有进程环境变量优先于文件中的同名配置，真实密钥不得提交到仓库。

```dotenv
# 网络、前端与数据库
HOST=127.0.0.1
PORT=7188
APP_BASE_URL=https://kegel.yourdomain.com
FRONTEND_BASE_PATH=/new/
DATABASE_URL=postgres://kegel:replace-with-password@127.0.0.1:5432/kegel
SNOWFLAKE_WORKER_ID=0

# 密钥与管理
APP_SECRET=your-super-long-and-secure-random-secret-key-at-least-32-chars
ADMIN_USER_IDS=12345,67890
# 敏感管理操作二选一：明文二级密码，或下文命令生成的加盐哈希
ADMIN_SECONDARY_PASSWORD=
ADMIN_POINTS_PASSWORD_HASH=

# LINUX DO Connect
LINUXDO_CLIENT_ID=your-connect-client-id
LINUXDO_CLIENT_SECRET=your-connect-client-secret
LINUXDO_REDIRECT_URI=https://kegel.yourdomain.com/api/auth/linuxdo/callback

# LINUX DO Credit
LDC_DONATION_ENABLED=true
LDC_LIVE=true
LDC_API_BASE=https://credit.linux.do
LDC_CLIENT_ID=your-credit-merchant-id
LDC_CLIENT_SECRET=your-credit-merchant-secret
DAILY_LDC_LIMIT=800
PAYMENT_LOG_PATH=/var/log/kegel/payments.jsonl

# 自动化
CHECKIN_TRIGGER_TOKEN=your-optional-token-to-open-checkin-via-webhook
CHECKIN_CONDITION_TOKEN=your-optional-bearer-token-for-condition-polling
```

`SNOWFLAKE_WORKER_ID` 取值为 0–1023；生产必须显式设置，多实例必须各不相同。`APP_SECRET` 在生产环境至少 32 字符。`LDC_DONATION_ENABLED` 控制赞助下单，`LDC_LIVE=false` 时商品兑换使用模拟发货。`DAILY_LDC_LIMIT=0` 仅停止 LDC 兑换，不影响签到积分；修改后需重启。

## 3. 数据库初始化

应用不会自动建表。先创建数据库和账户，再执行仓库提供的结构文件：

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/schema.sql
```

首次初始化后可用以下命令确认表可访问：

```bash
psql "$DATABASE_URL" -c 'SELECT COUNT(*) FROM checkin_settings;'
```

## 4. 启动后端

开发或前台运行：

```bash
uv run uvicorn app.server:app --host 127.0.0.1 --port 7188
```

仓库脚本会执行 `uv sync --frozen --no-dev` 并重启单机 uvicorn 进程：

```bash
scripts/update-backend.sh
```

健康检查为 `GET /health`，API 心跳为 `GET /api/heartbeat`。

## 5. 前端开发与发布

开发时在 `frontend/` 运行：

```bash
pnpm install
pnpm dev
```

Vite 将 `/api` 代理到 `http://127.0.0.1:7188`，并把 Origin 改写为 `http://localhost:7188`。生产构建的 base 为 `/new/`，因此后端必须设置 `FRONTEND_BASE_PATH=/new/`：

```bash
pnpm build
```

也可从仓库根目录发布；`DEPLOY_DIR` 是 Web 服务器对应 `/new/` 的静态目录：

```bash
DEPLOY_DIR=/var/www/kegel/new scripts/update-frontend.sh
```

## 6. 生产反向代理配置

反向代理只把 `/api/*` 与 `/health` 转发到 7188，并将前端构建产物托管在 `/new/`。History 模式路由必须回退到 `/new/index.html`。

### 6.1 Caddyfile 示例

```caddy
kegel.yourdomain.com {
    encode gzip zstd

    request_body {
        max_size 1MB
    }

    handle /api/* {
        reverse_proxy 127.0.0.1:7188 {
            header_up Host {host}
            header_up X-Real-IP {remote_host}
            header_up X-Forwarded-For {remote_host}
            header_up X-Forwarded-Proto {scheme}
        }
    }

    handle /health {
        reverse_proxy 127.0.0.1:7188
    }

    handle_path /new/* {
        root * /var/www/kegel/new
        try_files {path} /index.html
        file_server
    }

    redir / /new/ 302
}
```

### 6.2 Nginx 示例

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

    location /api/ {
        proxy_pass http://127.0.0.1:7188;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 15s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }

    location = /health {
        proxy_pass http://127.0.0.1:7188/health;
    }

    location /new/ {
        alias /var/www/kegel/new/;
        try_files $uri $uri/ /new/index.html;
    }

    location = / {
        return 302 /new/;
    }
}
```

`APP_BASE_URL` 应为站点公开源地址（如 `https://kegel.yourdomain.com`），不包含 `/new/`。Connect 后台回调地址须同步为 `/api/auth/linuxdo/callback`；LDC 商户通知地址为 `<APP_BASE_URL>/api/payments/ldc/notify`。

## 7. systemd 守护进程

在 `/etc/systemd/system/kegel.service` 创建：

```ini
[Unit]
Description=Kegel FastAPI Service
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/Kegel
EnvironmentFile=/var/www/Kegel/.env
ExecStart=/usr/local/bin/uv run --no-dev uvicorn app.server:app --host 127.0.0.1 --port 7188
Restart=always
RestartSec=5
LimitNOFILE=65535
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kegel
sudo systemctl status kegel
```

## 8. 数据备份与完整性自检

使用 `pg_dump` 创建 PostgreSQL 一致性备份：

```bash
pg_dump --format=custom --file="/backup/kegel_$(date +%Y%m%d_%H%M%S).dump" "$DATABASE_URL"
```

恢复前应在隔离环境验证备份：

```bash
createdb kegel_restore_check
pg_restore --exit-on-error --clean --if-exists --no-owner --dbname=kegel_restore_check /backup/kegel_YYYYMMDD_HHMMSS.dump
psql kegel_restore_check -c 'SELECT COUNT(*) FROM points_ledger;'
```

日常自检可检查连接、表及无效索引：

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c 'SELECT 1;'
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "SELECT n.nspname AS schema_name, c.relname AS index_name FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT i.indisvalid;"
```

数据库备份与支付日志需分别保存，并定期实际演练恢复。

### 8.1 支付请求与响应日志

默认写入项目根目录 `checkin.payments.jsonl`；可用 `PAYMENT_LOG_PATH` 指定位置。日志为 UTF-8 JSONL、追加写入、不自动轮转，新建文件权限为 `0600`，服务账户必须有目录写权限。

- 记录 `/api/shop`、`/api/shop/purchase`、`/api/donations`、`/api/donations/create`、`/api/payments/ldc/notify` 和 `/api/admin/points/add` 的请求与响应；二级密码始终脱敏。
- 记录服务端访问 `/lpay/`、`/epay/` 时的完整响应、HTTP 状态和异常。
- 使用 `exchange_id` 关联请求与响应；回调接受、拒绝和异常均写入事件。
- 认证头、Cookie、商户密钥、令牌和签名脱敏；订单号、交易号、金额和错误消息保留。
- 日志写入失败时，脱敏事件输出到标准错误，不改变支付结果。需轮转日志并监控磁盘空间。

赞助由浏览器直接提交到 LDC；服务端只能记录生成的支付表单及后续回调。浏览器回跳不确认到账，回调仍须完成签名、状态、商户、订单、金额和交易号校验。历史可疑订单需按商户订单号人工对账。

### 8.2 管理员敏感操作二级密码

管理员修改排名奖励、商品上架/编辑/下架和人工加积分时需要二级密码。可直接设置 `ADMIN_SECONDARY_PASSWORD`，也可仅保存 `ADMIN_POINTS_PASSWORD_HASH`。哈希采用 PBKDF2-HMAC-SHA256、600000 次迭代和随机 16 字节盐。

在自己的终端运行以下命令，输入两次二级密码（输入不回显），将输出整行原样写入 `.env`：

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

通过 shell 设置时须用单引号包住哈希，避免 `$` 被展开。单笔人工加分支持 1–100000000 整数积分；余额和 `admin_credit` 流水同事务提交，相同请求编号重试不会重复入账。

## 9. 部署边界

PostgreSQL 可供一个或多个应用实例连接；多实例的 `SNOWFLAKE_WORKER_ID` 必须各不相同，且调度职责需确保不会因重复启动造成重复任务。关键写流程使用 PostgreSQL 事务级咨询锁串行化。支付对账日志仍是各实例本机文件：多实例部署时应设置各自路径并集中采集、备份和检索，不能把单个本机文件视为全站完整日志。
