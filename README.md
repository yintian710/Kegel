# Kegel - 每日提肛打卡

基于 LINUX DO Connect 身份认证的每日提肛打卡站点。后端使用 Python 3.12+、FastAPI、Tortoise ORM 与 PostgreSQL，前端使用 Vue 3、Vite、TypeScript、Naive UI 与 Pinia。整体采用现代简约设计（纯净白底、深色字体与青绿点缀，告别沉重边框与背景图片），提供沉浸平滑的淡入淡出练习体验。

站点结构：
- **首页 `/`**：独立的每日三次手动打卡。今日已完成打卡时直接展示结算页、打卡奖励榜与奖励规则；未完成时展示初始页，点击或按键进入打卡准备阶段。首页不展示训练榜，训练的设置、进度和完成状态不会接管首页，也不会触发页面跳转。右侧保留隐藏称呼、自定义称呼和浏览器提醒设置。
- **练习 `/practice`**：训练过程在浏览器本地计时，支持手动和自动模式，每轮 1–20 次、每次 2–10 秒；新浏览器默认自动、10 次、每次 3 秒。每次分为「提～、放松、休息」，初始比例 45% / 40% / 15%；每段前 2/3 时间淡入，后 1/3 时间淡出。时间轴的两个分界点支持按 1% 调整，并显示各阶段秒数；阶段可设为 0% 以取消，训练时直接跳过，也可只保留一个阶段。「阶段分配」内可自定义三个阶段文字，每段最多 24 字，留空恢复默认文字，新配置从下一轮生效。「放弃本轮」仅结算已完整完成的次数，未完成任何一次时不产生记录。访客可练习；登录用户结束后自动上传本轮开始时间、结束时间和实际完成次数，归到当前账号。「每日训练榜」统计今日有效上传次数，「训练总榜」累计所有日期的有效上传次数，两榜各展示前 50 名，统一使用独立训练记录。「我的训练记录」展示个人最近 50 轮明细。断网不影响本地训练，待上传记录保留，恢复网络后可在时效内重传。训练不影响正式打卡、积分或奖励；进入训练页仅通过首页按钮或顶部导航，完成后仍留在训练页。
- **商店 `/shop`**：展示站内积分钱包余额、上架商品展示列表（后台可增删改）、积分流水，并提供前往独立赞助页面的链接。
- **赞助 `/donate`**：独立的 LDC 赞助支持页面，提供赞助输入与快捷档位，明确说明**赞助不会增加站内积分**；展示已核验到账的公开赞助榜和个人赞助记录。
- **管理后台 `/admin`**：提供概览监控卡片、基础规则配置、排名奖励、商品管理（添加、修改、下架）、练习触发记录查询和用户余额。

上述五个页面统一使用 Vue 前端的 `AppLayout` 布局及复用组件，共享菜单顺序、当前页高亮、账户及登录退出行为，支持窄屏横向滚动。首页初始页也显示导航；管理后台布局在导航下方。

## 启动与配置

```bash
cp .env.example .env
# 编辑 .env，填写 PostgreSQL、Connect 凭据、随机密钥和管理员 LINUX DO 用户 ID
uv sync
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/schema.sql
uv run uvicorn app.server:app --host 127.0.0.1 --port 7188
```

打开 `http://localhost:7188`；前端开发在 `frontend/` 运行 `pnpm dev`，管理页面为 `/admin`。生产构建运行 `pnpm build`，静态站点发布到 `/new/` 时设置 `FRONTEND_BASE_PATH=/new/`。程序内置 `.env` 加载，已存在的进程环境变量优先。不要提交 `.env`、数据库凭据或真实密钥。

后端健康检查为 `/health`，API 心跳为 `/api/heartbeat`；图标继续由 `/api/icon` 提供，图片文件位于 `app/assets/img/`。

签到必须通过 Connect OAuth 登录，不提供演示身份。将应用回调地址配置为 `http://localhost:7188/api/auth/linuxdo/callback`，部署后改为公开 HTTPS 地址并同步 `APP_BASE_URL` 与 `LINUXDO_REDIRECT_URI`。未配置 OAuth 时无法签到，也无法进入管理后台。管理员按登录身份识别：`ADMIN_USER_IDS` 未设置时所有管理接口拒绝访问；触发接口同样需要独立的 `CHECKIN_TRIGGER_TOKEN`。

首页、公开状态及练习接口无需登录。配置完整的 OAuth 凭据后，商店、赞助页和管理页仍要求登录。访客练习不记录正式打卡、不累计排行榜、不领取奖励。登录 Cookie 有效期为 **5 天**，有效期内访问时自动续至访问后的 5 天；过期或退出后需重新登录。

| 环境变量 | 用途与默认值 |
| --- | --- |
| `HOST` | 监听地址，默认 `127.0.0.1`。 |
| `PORT` | 监听端口，默认 `7188`。 |
| `APP_BASE_URL` | 对外完整源地址，默认 `http://localhost:<PORT>`；生产使用 HTTPS。 |
| `FRONTEND_BASE_PATH` | 前端路径前缀，开发默认 `/`；生产构建发布到 `/new/` 时设为 `/new/`。 |
| `DATABASE_URL` | PostgreSQL 连接串，默认连接本机 `kegel` 数据库；表结构由 `sql/schema.sql` 初始化。 |
| `SNOWFLAKE_WORKER_ID` | 雪花 ID 机器号，0–1023，默认 `0`；生产必须显式设置，多实例各不相同。 |
| `APP_SECRET` | 会话签名密钥。生产必须设置至少 32 字符的随机值；仅本地开发允许启动时自动生成。 |
| `ADMIN_USER_IDS` | 管理员的 LINUX DO 用户 ID，纯数字、逗号分隔；仅这些账号登录后可访问管理页与管理接口，未设置则无人可进。 |
| `ADMIN_SECONDARY_PASSWORD` | 管理员敏感操作的明文二级密码；可与下一项二选一。 |
| `ADMIN_POINTS_PASSWORD_HASH` | 管理员敏感操作二级密码的 PBKDF2 加盐哈希。 |
| `LINUXDO_CLIENT_ID` / `LINUXDO_CLIENT_SECRET` | Connect OAuth 应用凭据，登录必需。 |
| `LINUXDO_REDIRECT_URI` | OAuth 回调地址，默认 `<APP_BASE_URL>/api/auth/linuxdo/callback`。 |
| `LDC_DONATION_ENABLED` | 默认 `false`；开启并配置商户凭据后允许创建真实 LDC 赞助订单。 |
| `LDC_LIVE` | 默认 `false`，商品兑换模拟发货；设为 `true` 后调用真实发货接口。 |
| `LDC_API_BASE` | 官方商户网关，默认 `https://credit.linux.do`。 |
| `LDC_CLIENT_ID` / `LDC_CLIENT_SECRET` | Credit 商户凭据，用于赞助签名、通知验签和商品发货。 |
| `DAILY_LDC_LIMIT` | 全站每日 LDC 兑换额度，默认 `800`；`0` 停止兑换但不影响签到积分。 |
| `PAYMENT_LOG_PATH` | 本机支付 JSONL 日志路径；留空为项目根目录 `checkin.payments.jsonl`。 |
| `CHECKIN_TRIGGER_TOKEN` | 外部开放触发接口 `X-Trigger-Token` 口令；留空禁用。 |
| `CHECKIN_CONDITION_TOKEN` | 可选条件接口请求的 Bearer 令牌。 |

凭据与全站每日 LDC 兑换额度由环境变量配置；每日截止时间、步骤间隔、奖励区间与 `condition_url` 通过管理页或管理 API 保存到数据库。每日奖励为本地整数站内积分入账，无需任何支付凭据。LDC 赞助与站内积分独立，不提供充值或购买比例配置。

## 每日规则与开放方式

日期和每日截止时间均按 `Asia/Shanghai` 计算。当天在开放后才能正式打卡；默认每日 `22:00` 到点开放，也可由管理员手动提前开放或由外部条件触发。首页打卡固定三次手动操作、每次默认至少间隔 8 秒。名次在打卡完成时分配，同一 OAuth 用户每天只能获得一个名次；站内积分奖励随完成时的名次固定。默认第 1–10 名各 `1000` 站内积分，第 11–20 名各 `500`，第 21–50 名各 `100`；奖励区间可配置，金额为整数。首个连续工作日使用排名基础奖励，之后每连续多一个工作日增加 `1%`，最高增加 `100%`；周末不增加天数，也不会中断连续记录，计算结果有小数时向下取整。用户完成后主动领取，同一天的同一奖励只入账一次。独立训练不生成打卡名次或奖励。

首页打卡由 `/api/session/start`、`/api/session/step`、`/api/session/complete` 计时及结算。独立训练的开始、继续和计时在本地处理，结束后通过 `POST /api/practice/records` 上传，使用独立的记录表；`GET /api/practice` 返回登录身份、每日榜、总榜和个人明细。后端按登录身份归属记录，不接受客户端指定归属；每轮实际完成次数 1–20、每次 2–10 秒，总时长至少为次数乘每次时长。开始时间须在服务器时间一小时内，结束时间须在五分钟内，两者最多允许快于服务器 30 秒。同一用户的时间区间不能重叠，端点相接允许；同一轮原样重传不会重复累计，改动已上传内容会被拒绝。两个系统均保留十分钟未继续失效规则。升级时保留正式打卡、奖励和已上传的 `training_records`，自动迁移训练时长上限；训练榜不混入旧的打卡累计次数。旧本地记录没有起止时间，不补造数据上传。

首页设置支持隐藏「提肛」或自定义称呼，设置会保存在当前浏览器并用于所有页面。直接访问 `/?hide_tigang=1` 可隐藏这些文字，`/?exercise_name=运动` 可自定义称呼；`?hide_tigang=0` 恢复显示。标题、提示和辅助说明同步处理。

提醒设置支持整点、半点或两者同时开启，由用户点击后申请浏览器通知权限。需要 HTTPS 或 localhost，并保持页面打开；浏览器休眠或系统限制可能延迟通知，恢复后不会补发过期提醒。关闭页面后不提供定时推送。

全站每日 LDC 兑换额度由环境变量 `DAILY_LDC_LIMIT` 配置为整数 LDC，默认 **800 LDC**，修改后需重启服务生效。额度按北京时间每天重置，并按商品的精确 `ldc_amount` 金额累计；`pending`、`success`、`simulated` 和 `uncertain` 订单占用额度，`failed` 订单释放额度。统计与接口展示均使用两位小数字符串。单笔商品的 LDC 金额大于剩余额度时整笔拒绝。设置为 `0` 会停止 LDC 兑换，但不影响打卡、签到积分领取或钱包入账。

签到奖励不受 LDC 兑换额度限制；例如默认首档的 1000 站内积分可正常领取，即使当日 LDC 兑换额度为 0。

管理 API 按登录身份鉴权：请求须携带该管理员登录后的 `linuxdo_session` Cookie（可从浏览器开发者工具复制），请求体为 JSON。以下示例假定已在 shell 中设置 `ADMIN_SESSION`：

```bash
# 立即开放今天的签到
curl -X POST http://localhost:7188/api/admin/open \
  -b "linuxdo_session=$ADMIN_SESSION" \
  -H 'Content-Type: application/json' -d '{}'

# 配置每日到点开放时间、步骤间隔、整数站内积分奖励和可选条件地址
curl -X POST http://localhost:7188/api/admin/settings \
  -b "linuxdo_session=$ADMIN_SESSION" \
  -H 'Content-Type: application/json' \
  -d '{"deadline":"22:00","min_step_seconds":8,"reward_tiers":[{"through":10,"amount":1000},{"through":20,"amount":500},{"through":50,"amount":100}],"condition_url":"https://your-service.example/checkin-condition"}'

# 定时任务或外部服务触发今天开放
curl -X POST http://localhost:7188/api/trigger/open \
  -H "X-Trigger-Token: $CHECKIN_TRIGGER_TOKEN" \
  -H 'Content-Type: application/json' -d '{}'
```

服务每 30 秒检查可选的 `condition_url`。条件服务须返回 JSON `{"open":true}` 才触发当天开放；设置 `CHECKIN_CONDITION_TOKEN` 后请求携带 `Authorization: Bearer <token>`。条件地址留空即关闭条件轮询。请仅配置可信的条件服务地址。

## 访问记录与人工复核

访问记录关联已登录的 OAuth 身份，或未登录用户的签名匿名 Cookie，并记录散列后的 IP 与访问时间、频次。规律性访问等模式可使当天签到进入人工复核；管理员可在管理页面核实并批准，或调用：

```bash
curl -X POST http://localhost:7188/api/admin/review \
  -b "linuxdo_session=$ADMIN_SESSION" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"123","approved":true}'
```

这些记录和步骤间隔只辅助识别异常，不能保证操作者是真人，也不应仅凭共享 IP 判定用户身份。

## 站内积分、商店与独立赞助

- **积分与商店 (`/shop`)**：每日打卡奖励为整数站内积分，领取后计入个人钱包。商店展示当前积分余额、积分入账流水、LDC 商品兑换卡片，以及用户的兑换发货记录。
  - **管理员加积分**：后台“记录查询 → 用户积分余额”支持按用户名或用户 ID 搜索站内已有用户，选择用户后输入增加积分和二级密码。二级密码仅以加盐哈希保存在 `ADMIN_POINTS_PASSWORD_HASH`；未配置时禁用加积分。每笔加分记录 `admin_credit` 流水，重试同一请求不会重复入账，用户可在商店流水中查看。单笔为 1–100000000 整数积分；不直接改变 LDC 兑换额度。
  - **品类与配置**：商品品类固定为 `LDC`。后台新建或编辑商品时，选择品类、输入积分售价、发货 LDC 数量、单人每日限购数及全站每日总限购数（0 为不限）。
  - **购买自动发货**：确认兑换后，系统先在写事务内扣减积分、保存 `pending` 订单并提交，再调用 Linux DO Credit 商户接口 (`POST /lpay/distribute`) 转账。返回有效 `data.trade_no` 即为成功，无需 `code` 字段；明确拒绝才自动退款，超时或结果不明保留扣分与限额，订单标为「待核对」。前端为一次兑换保留请求编号，重试返回原订单，不重复扣分或分发。未配置商户凭据时运行于模拟发货模式。
  - **人工对账**：管理后台「自动发货与兑换记录」中，待核对订单提供「已发货」和「未发货并退分」两个操作。务必先到 Credit 商户后台确认这笔转账是否真的发出：已发出选前者，保留扣分；没发出选后者，退还积分并释放额度。两个操作都需要二级密码，且每个订单只能处理一次。
  - **每日兑换额度**：商品按 `ldc_amount` 精确金额占用全站额度；处理中、成功、模拟和待核对订单占额，失败订单释放额度。额度按北京时间每日重置，设为 `0` 仅停止兑换。
- **独立赞助 (`/donate`)**：登录后自行输入 **0.01–10000.00 LDC**，最多两位小数；页面不预填金额，快捷金额仅辅助填写。提交后跳转官方 LDC 支付平台。赞助**不会增加站内积分**。生产环境配置 `LDC_DONATION_ENABLED=true`、商户 `LDC_CLIENT_ID` / `LDC_CLIENT_SECRET` 和公网 HTTPS `APP_BASE_URL`。异步通知地址为 `<APP_BASE_URL>/api/payments/ldc/notify`。
- **赞助榜**：页面公开展示已确认到账的 LDC 赞助榜（按累计赞助金额排序，显示排名、用户名、总额及次数），登录用户可查看自己的赞助订单。只有服务端通过 MD5 验签及订单对账后才会计入榜单，重复通知不会重复累计，浏览器跳转回页面不会确认到账。
- **支付对账日志**：默认追加保存到项目根目录 `checkin.payments.jsonl`，可用 `PAYMENT_LOG_PATH` 指定本机位置。记录兑换、赞助接口及商户回调的请求和响应、外部分发原始响应、HTTP 错误、网络异常及回调拒绝原因；认证凭据、Cookie 和签名脱敏。日志不自动轮转或删除，需单独备份并监控磁盘空间。
## 部署边界

PostgreSQL 可供单实例或多实例后端连接；多实例的 `SNOWFLAKE_WORKER_ID` 必须各不相同，关键写流程使用 PostgreSQL 事务级咨询锁串行化。生产应使用 HTTPS 反向代理，将 `/api` 转发到 7188，并把前端构建产物静态托管到 `/new/`。支付对账日志仍是各实例的本机文件，多实例部署需分别采集和备份。还应配置至少 32 字符的随机 `APP_SECRET`、独立管理与触发口令，并保护数据库、备份及日志中的身份、访问和交易记录。

`api.md` 与 `doc.md` 保留官方参考资料快照；本 README 描述当前服务。真实 OAuth 登录及真实 LDC 收款仍需使用自己的应用和商户凭据做线上联调。

## 行为回归测试

运行测试命令：

```bash
uv run pytest
```

测试使用 `pgserver` 启动临时 PostgreSQL，依赖已由 `uv sync` 安装，无需手动准备测试数据库。
