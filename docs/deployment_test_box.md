# 测试环境部署（同域名 · 子路径 /box · 新端口）

> 目标：在**同一个域名**下新增一套测试环境，所有页面挂在 `https://<域名>/box/`，后端使用**新端口**，与生产互不干扰。
> 适用：抽卡等新功能上线前的联调/验收。
> 配套文件：[.env.box.example](../.env.box.example)、[deploy/nginx-box.conf](../deploy/nginx-box.conf)

## 1. 部署拓扑

| 项目 | 生产 | 测试（/box） |
|---|---|---|
| 访问地址 | `https://<域名>/` | `https://<域名>/box/` |
| 后端端口 | 7188 | **7190** |
| 数据库 | `kegel` | **`kegel_box`（独立）** |
| `FRONTEND_BASE_PATH` | `/` | **`/box/`** |
| `APP_BASE_URL` | `https://<域名>` | `https://<域名>`（同 Origin，不含路径） |
| 前端构建 base | `/` | **`/box/`** |
| 前端 API 前缀 | `/api` | **`/box/api`** |
| Cookie 路径 | `/` | **`/box`（自动派生，与主站隔离）** |
| 静态目录 | `/srv/kegel/site` | **`/srv/kegel/site-box`** |
| 支付日志 | 生产路径 | **`/opt/kegel-box/checkin.payments.jsonl`** |

> `APP_BASE_URL` 只写 `scheme://host[:port]`，**不能带 `/box`**。浏览器 POST 的 `Origin` 头只有 Origin 部分，后端用它做来源校验；带路径会导致所有 POST 403。
> 测试前端回调 `/box/...` 由 `FRONTEND_BASE_PATH=/box/` 自动拼出，**Cookie 作用路径 `COOKIE_PATH` 也自动变为 `/box`**，无需额外配置，浏览器会把测试站与主站的两套同名 Cookie 按路径区分开。

## 2. 第一步：准备独立数据库

```bash
# 新建测试库（示例）
createdb -h 127.0.0.1 -U postgres kegel_box
# 用权威 schema 建表（幂等）
psql "postgres://postgres:postgres@127.0.0.1:5432/kegel_box" -v ON_ERROR_STOP=1 -f sql/schema.sql
```

## 3. 第二步：准备测试后端配置

```bash
cp .env.box.example .env.box
# 按注释填写：APP_BASE_URL、APP_SECRET（与生产不同）、LINUXDO_* 回调、独立数据库等
```

关键项：
- `PORT=7190`
- `FRONTEND_BASE_PATH=/box/`
- `APP_BASE_URL=https://<域名>`（不带 /box）
- `DATABASE_URL=.../kegel_box`
- `SNOWFLAKE_WORKER_ID` 用与生产不同的值
- `APP_SECRET` 用与生产不同的值（≥32 字符）
- `LINUXDO_REDIRECT_URI=https://<域名>/box/api/auth/linuxdo/callback`

## 4. 第三步：构建并发布测试前端

```bash
cd frontend
VITE_BASE=/box/ VITE_API_BASE=/box/api pnpm install --frozen-lockfile
VITE_BASE=/box/ VITE_API_BASE=/box/api pnpm build
# 发布到测试静态目录（与生产目录分开）
rsync -a --delete dist/ /srv/kegel/site-box/
```

> 必须同时设置两个变量：
> - `VITE_BASE=/box/` 决定静态资源与 Vue Router 的 base（否则路由和 `/assets/*` 会 404）。
> - `VITE_API_BASE=/box/api` 决定前端请求前缀、登录/退出地址与 logo 图标地址。
> 不设置时默认仍为 `/` 与 `/api`，生产构建不受影响。

## 5. 第四步：启动测试后端（新端口）

先确认代码目录（建议与生产分开，如 `/opt/kegel-box`），然后加载 `.env.box` 启动：

```bash
cd /opt/kegel-box
uv sync --frozen --no-dev
set -a; source .env.box; set +a
nohup uv run --no-dev uvicorn app.server:app --host 127.0.0.1 --port 7190 \
    >> run/uvicorn-box.log 2>&1 &
echo $! > run/uvicorn-box.pid
```

或使用 systemd（示例）：

```ini
# /etc/systemd/system/kegel-box.service
[Unit]
Description=Kegel test env (/box)
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/kegel-box
EnvironmentFile=/opt/kegel-box/.env.box
ExecStart=/usr/local/bin/uv run --no-dev uvicorn app.server:app --host 127.0.0.1 --port 7190
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now kegel-box
curl -fsS http://127.0.0.1:7190/health    # 应为 healthy
```

### 5.1 测试环境免登录（AUTO_LOGIN，仅测试）

`/box` 测试环境可直接固定管理员用户进入，不走 LINUX DO OAuth：

```bash
AUTO_LOGIN_ENABLED=true
AUTO_LOGIN_USER_ID=1
AUTO_LOGIN_USERNAME=yintian
ADMIN_USER_IDS=1        # 必须包含上面的 AUTO_LOGIN_USER_ID
```

- 仅当 `AUTO_LOGIN_ENABLED=true` 且显式配置 `AUTO_LOGIN_USER_ID`（纯数字）时生效；**生产 .env 绝不能设置这两项**。
- 开启后，服务端在无会话时自动注入该固定用户；该 ID 在 `ADMIN_USER_IDS` 内即可直接访问管理后台。

## 6. 第五步：Nginx 反代

> 注：若服务器用 **Caddy**（本机即如此），改用下面的 Caddy 片段，放在 site 的 `(kegel_v2)` 片段内、catch-all `handle` 之前：
> ```
> handle /box/api { uri strip_prefix /box; reverse_proxy 127.0.0.1:7190 }
> handle /box/api/* { uri strip_prefix /box; reverse_proxy 127.0.0.1:7190 }
> handle /box/health { uri strip_prefix /box; reverse_proxy 127.0.0.1:7190 }
> redir /box /box/ 308
> handle_path /box/* {
>     root * /srv/kegel/site-box
>     try_files {path} /index.html
>     file_server
> }
> ```

把 [deploy/nginx-box.conf](../deploy/nginx-box.conf) 的 `location` 片段加进现有 HTTPS `server {}`（与生产同一域名），然后：

```bash
nginx -t && systemctl reload nginx
```

路由规则回顾：
- `/box/api/*` → `127.0.0.1:7190/api/*`（去掉 `/box` 前缀）
- `/box/*` → 静态 `/srv/kegel/site-box`，SPA 回退到 `/box/index.html`
- 生产 `/` 与 `/api/*` 原样不动

## 7. 第六步：登记 OAuth 回调

在 LINUX DO Connect 应用后台，把测试回调地址加入允许列表：
```
https://<域名>/box/api/auth/linuxdo/callback
```
（生产回调 `https://<域名>/api/auth/linuxdo/callback` 保持不变。）

## 8. 验收清单

```bash
# 1) 后端健康
curl -fsS http://127.0.0.1:7190/health
# 2) 经反代访问测试 API（应返回统一信封 JSON）
curl -fsS https://<域名>/box/api/status | head -c 200
# 3) 测试前端首页 200 且资源指向 /box/
curl -fsS https://<域名>/box/ | grep -o '/box/assets/[^"]*' | head
# 4) 生产不受影响
curl -fsS https://<域名>/api/status | head -c 200
```

浏览器手动确认：
- 打开 `https://<域名>/box/`，页面正常、logo 与接口走 `/box/api`。
- 在 `/box` 登录后，主站 `/` 的登录态**不被覆盖**（反之亦然）。
- 抽卡等新功能只在 `/box` 可见（若功能开关按环境区分）。
- 站内跳转（`/box/shop`、刷新深链）不 404（SPA 回退生效）。

## 9. 隔离与注意事项

1. **数据库隔离**：测试库 `kegel_box` 与生产库分离，schema 变更先在测试库验证。
2. **密钥隔离**：`APP_SECRET` 不同 → 两个站的会话 Cookie 互不认可；配合 Cookie 路径 `/box` 双重隔离。
3. **Cookie 同名不同路径**：浏览器会同时保存 `path=/`（生产）与 `path=/box`（测试）两份同名 Cookie，互不覆盖。
4. **端口隔离**：7190 仅监听 127.0.0.1，由 Nginx 对外；防火墙不暴露该端口。
5. **支付/发货**：测试环境建议 `LDC_DONATION_ENABLED=false`、`LDC_LIVE=false`（模拟发货），支付日志单独路径。
6. **定时任务**：`tick()` 由每个后端进程各自启动；两个实例同时跑会对同一数据库重复调度，但两实例数据库不同，互不影响。**切勿让测试实例连生产库**。
7. **前端构建**：生产用默认 `pnpm build`（base `/`）；测试必须带 `VITE_BASE=/box/ VITE_API_BASE=/box/api`，否则白屏/接口 404。

## 10. 回滚

- 关闭测试：`systemctl stop kegel-box`（或 kill pid），Nginx 移除 `/box` 片段后 `nginx -t && systemctl reload nginx`。
- 测试数据清理：直接 drop `kegel_box` 库（不影响生产）。
