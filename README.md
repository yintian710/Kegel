# Kegel - 每日提肛打卡

基于 LINUX DO Connect 身份认证的每日提肛打卡站点。使用 Python 3.14 及以上版本的标准库与 SQLite，无需安装第三方依赖。整体采用现代简约设计（纯净白底、深色字体与青绿点缀，告别沉重边框与背景图片），提供沉浸平滑的淡入淡出练习体验。

站点结构：
- **首页 `/`**：访客打开时停留在主页，不会自动进入打卡。首页只保留每日三次手动打卡：先显示「开始第 1 次？」，点击才真正开始；计时及文字过渡结束后，点击下一次提示继续。顶部导航和完成卡片提供「提肛练习」入口。右下角只保留隐藏称呼、自定义称呼和浏览器提醒设置，不再显示自动练习方式、次数、间隔或自动运行控件。
- **练习 `/practice`**：无需登录即可进入，练习卡片只展示方式、次数和间隔；隐藏称呼、自定义称呼及整点/半点通知统一放在右下角「设置」。自动模式支持每轮 1–20 次、间隔 2–5 秒，每一次（含第一次）在本次计时内先淡入再淡出。新浏览器默认自动、10 次、间隔 3 秒；已保存过配置的浏览器继续使用原设置。练习设置可随时收起或展开，每日排名固定显示在练习区域下方，按今日完成的练习次数排序。练习卡片上方提供「← 返回首页」，顶部导航在滚动时保持可见。下方倒计时提示行固定不动，只更新剩余秒数。手动和自动模式完成后均可再开一轮，不覆盖每日奖励记录。修改显示和提醒设置不会覆盖练习配置，也不会让首页进入自动模式。
- **商店 `/shop`**：展示站内积分钱包余额、上架商品展示列表（后台可增删改）、积分流水，并提供前往独立赞助页面的链接。
- **赞助 `/donate`**：独立的 LDC 赞助支持页面，提供赞助输入与快捷档位，明确说明**赞助不会增加站内积分**；展示已核验到账的公开赞助榜和个人赞助记录。
- **管理后台 `/admin`**：提供概览监控卡片、基础规则配置、排名奖励、商品管理（添加、修改、下架）、练习触发记录查询和用户余额。

## 启动与配置

```bash
cp .env.example .env
# 编辑 .env，填写 Connect 凭据、随机密钥和管理口令
python3 app.py
```

打开 `http://localhost:8000`；管理页面为 `/admin`。程序内置 `.env` 加载，已存在的进程环境变量优先。不要提交 `.env`、数据库或真实密钥。

签到必须通过 Connect OAuth 登录，不提供演示身份。将应用回调地址配置为 `http://localhost:8000/auth/linuxdo/callback`，部署后改为公开 HTTPS 地址并同步 `APP_BASE_URL` 与 `LINUXDO_REDIRECT_URI`。未配置 OAuth 时无法签到。`ADMIN_TOKEN` 未设置时所有管理接口拒绝访问；触发接口同样需要独立的 `CHECKIN_TRIGGER_TOKEN`。

首页、公开状态及练习接口无需登录。配置完整的 OAuth 凭据后，商店、赞助页和管理页仍要求登录。访客练习不记录正式打卡、不累计排行榜、不领取奖励。登录 Cookie 有效期为 **5 天**，有效期内访问时自动续至访问后的 5 天；过期或退出后需重新登录。

| 环境变量 | 用途与默认值 |
| --- | --- |
| `CHECKIN_DB` | SQLite 文件路径，默认 `checkin.db`。旧 `redpacket.db` 保留但不再使用。 |
| `HOST` | 监听地址，默认 `127.0.0.1`。 |
| `PORT` | 监听端口，默认 `8000`。 |
| `APP_BASE_URL` | 对外完整地址，默认 `http://localhost:<PORT>`；生产使用 HTTPS。 |
| `APP_SECRET` | 会话签名密钥。生产必须设置至少 32 字符的随机值；仅本地开发允许每次启动自动生成，重启会使旧会话失效。 |
| `ADMIN_TOKEN` | 管理接口 `X-Admin-Token` 口令；未设置则拒绝管理访问。 |
| `LINUXDO_CLIENT_ID` | Connect OAuth 应用 Client ID，登录必需。 |
| `LINUXDO_CLIENT_SECRET` | Connect OAuth 应用 Client Secret，登录必需。 |
| `LINUXDO_REDIRECT_URI` | OAuth 回调地址，默认 `<APP_BASE_URL>/auth/linuxdo/callback`。 |
| `LDC_DONATION_ENABLED` | 默认 `false`；开启并配置商户凭据后允许创建真实 LDC 赞助订单。 |
| `LDC_API_BASE` | 官方商户网关，默认 `https://credit.linux.do`。 |
| `LDC_CLIENT_ID` / `LDC_CLIENT_SECRET` | Credit 商户 API Key，用于赞助订单签名及支付通知验签。 |
| `DAILY_LDC_LIMIT` | 全站每日 LDC 兑换额度，整数 LDC，默认 `800`；`0` 停止兑换但不影响签到积分。修改后需重启服务生效。 |
| `CHECKIN_TRIGGER_TOKEN` | 外部开放触发接口 `X-Trigger-Token` 口令；不设置则不能使用该入口。 |
| `CHECKIN_CONDITION_TOKEN` | 可选条件接口请求的 Bearer 令牌；仅发给配置的 `condition_url`。 |

凭据与全站每日 LDC 兑换额度由环境变量配置；每日截止时间、步骤间隔、奖励区间与 `condition_url` 通过管理页或管理 API 保存到数据库。每日奖励为本地整数站内积分入账，无需任何支付凭据。LDC 赞助与站内积分独立，不提供充值或购买比例配置。

## 每日规则与开放方式

日期和每日截止时间均按 `Asia/Shanghai` 计算。当天在开放后才能开始签到；默认每日 `22:00` 到点开放，也可由管理员手动提前开放或由外部条件触发。手动模式默认三次、每次至少间隔 8 秒；自动模式按所选次数和间隔完成。名次在本轮完成时分配，同一 OAuth 用户每天只能获得一个名次；站内积分奖励随完成时的名次固定。默认第 1–10 名各 `1000` 站内积分，第 11–20 名各 `500`，第 21–50 名各 `100`；奖励区间可配置，金额为整数。用户完成后主动领取，同一天的同一奖励只入账一次。

每次练习均由服务端计时：第一次调用 `POST /api/session/start`，后续调用 `POST /api/session/step`，最后一次计时结束调用 `POST /api/session/complete`。自动模式请求示例：`{"mode":"auto","repetitions":20,"interval_seconds":2}`。完成及领取时校验本轮全部触发记录和时间间隔，修改浏览器倒计时不能提前完成。达到十分钟仍未继续，本轮失效；刷新可恢复有效会话。

今日练习榜按已完成轮次的总次数排序，登录用户在打卡尚未开放时也可累计，待审核用户和访客不计入。自动模式完成后可再次开始，每日打卡名次和奖励仍只生成一份，重复训练不会重复发奖。

首页设置支持隐藏「提肛」或自定义称呼，设置会保存在当前浏览器并用于所有页面。直接访问 `/?hide_tigang=1` 可隐藏这些文字，`/?exercise_name=运动` 可自定义称呼；`?hide_tigang=0` 恢复显示。标题、提示和辅助说明同步处理。

提醒设置支持整点、半点或两者同时开启，由用户点击后申请浏览器通知权限。需要 HTTPS 或 localhost，并保持页面打开；浏览器休眠或系统限制可能延迟通知，恢复后不会补发过期提醒。关闭页面后不提供定时推送。

全站每日 LDC 兑换额度由环境变量 `DAILY_LDC_LIMIT` 配置为整数 LDC，默认 **800 LDC**，修改后需重启服务生效。额度按北京时间每天重置，并按商品的精确 `ldc_amount` 金额累计；`pending`、`success`、`simulated` 和 `uncertain` 订单占用额度，`failed` 订单释放额度。统计与接口展示均使用两位小数字符串。单笔商品的 LDC 金额大于剩余额度时整笔拒绝。设置为 `0` 会停止 LDC 兑换，但不影响打卡、签到积分领取或钱包入账。

签到奖励不受 LDC 兑换额度限制；例如默认首档的 1000 站内积分可正常领取，即使当日 LDC 兑换额度为 0。

管理 API 使用 `X-Admin-Token`，请求体为 JSON。以下示例假定已在 shell 中设置对应口令：

```bash
# 立即开放今天的签到
curl -X POST http://localhost:8000/api/admin/open \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{}'

# 配置每日到点开放时间、步骤间隔、整数站内积分奖励和可选条件地址
curl -X POST http://localhost:8000/api/admin/settings \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"deadline":"22:00","min_step_seconds":8,"reward_tiers":[{"through":10,"amount":1000},{"through":20,"amount":500},{"through":50,"amount":100}],"condition_url":"https://your-service.example/checkin-condition"}'

# 定时任务或外部服务触发今天开放
curl -X POST http://localhost:8000/api/trigger/open \
  -H "X-Trigger-Token: $CHECKIN_TRIGGER_TOKEN" \
  -H 'Content-Type: application/json' -d '{}'
```

服务每 30 秒检查可选的 `condition_url`。条件服务须返回 JSON `{"open":true}` 才触发当天开放；设置 `CHECKIN_CONDITION_TOKEN` 后请求携带 `Authorization: Bearer <token>`。条件地址留空即关闭条件轮询。请仅配置可信的条件服务地址。

## 访问记录与人工复核

访问记录关联已登录的 OAuth 身份，或未登录用户的签名匿名 Cookie，并记录散列后的 IP 与访问时间、频次。规律性访问等模式可使当天签到进入人工复核；管理员可在管理页面核实并批准，或调用：

```bash
curl -X POST http://localhost:8000/api/admin/review \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"123","approved":true}'
```

这些记录和步骤间隔只辅助识别异常，不能保证操作者是真人，也不应仅凭共享 IP 判定用户身份。

## 站内积分、商店与独立赞助

- **积分与商店 (`/shop`)**：每日打卡奖励为整数站内积分，领取后计入个人钱包。商店展示当前积分余额、积分入账流水、LDC 商品兑换卡片，以及用户的兑换发货记录。
  - **管理员加积分**：后台“记录查询 → 用户积分余额”支持按用户名或用户 ID 搜索站内已有用户，选择用户后输入增加积分和二级密码。二级密码仅以加盐哈希保存在 `ADMIN_POINTS_PASSWORD_HASH`；未配置时禁用加积分。每笔加分记录 `admin_credit` 流水，重试同一请求不会重复入账，用户可在商店流水中查看。单笔为 1–100000000 整数积分；不直接改变 LDC 兑换额度。
  - **品类与配置**：商品品类固定为 `LDC`。后台新建或编辑商品时，选择品类、输入积分售价、发货 LDC 数量、单人每日限购数及全站每日总限购数（0 为不限）。
  - **购买自动发货**：确认兑换后，系统先在写事务内扣减积分、保存 `pending` 订单并提交，再调用 Linux DO Credit 商户接口 (`POST /lpay/distribute`) 转账。返回有效 `data.trade_no` 即为成功，无需 `code` 字段；明确拒绝才自动退款，超时或结果不明保留扣分与限额等待对账。前端为一次兑换保留请求编号，重试返回原订单，不重复扣分或分发。未配置商户凭据时运行于模拟发货模式。
  - **每日兑换额度**：商品按 `ldc_amount` 精确金额占用全站额度；处理中、成功、模拟和待核对订单占额，失败订单释放额度。额度按北京时间每日重置，设为 `0` 仅停止兑换。
- **独立赞助 (`/donate`)**：登录后自行输入 **0.01–10000.00 LDC**，最多两位小数；页面不预填金额，快捷金额仅辅助填写。提交后跳转官方 LDC 支付平台。赞助**不会增加站内积分**。生产环境配置 `LDC_DONATION_ENABLED=true`、商户 `LDC_CLIENT_ID` / `LDC_CLIENT_SECRET` 和公网 HTTPS `APP_BASE_URL`。异步通知地址为 `<APP_BASE_URL>/payments/ldc/notify`。
- **赞助榜**：页面公开展示已确认到账的 LDC 赞助榜（按累计赞助金额排序，显示排名、用户名、总额及次数），登录用户可查看自己的赞助订单。只有服务端通过 MD5 验签及订单对账后才会计入榜单，重复通知不会重复累计，浏览器跳转回页面不会确认到账。
- **支付对账日志**：默认追加保存到数据库同目录的 `checkin.payments.jsonl`，可用 `PAYMENT_LOG_PATH` 指定位置。记录兑换、赞助接口及商户回调的请求和响应、外部分发原始响应、HTTP 错误、网络异常及回调拒绝原因；保留订单号、交易号、金额和关联编号，认证凭据、Cookie、签名脱敏。日志不自动轮转或删除，需单独备份并监控磁盘空间。仅能记录启用后的流量。
## 部署边界

SQLite 部署仅支持单主机、单应用进程。不要让多个进程或多台主机同时运行并共享该数据库；单应用进程负责调度。生产应使用 HTTPS 反向代理，配置至少 32 字符的随机 `APP_SECRET`、独立管理与触发口令，并保护数据库及备份中的身份、访问和交易记录。迁移旧项目时默认新建 `checkin.db`，不读取或转换旧红包数据库。若现有签到数据库包含旧版支付记录，迁移仅保留历史审计，不将已支付的 LDC 转成站内积分。

`api.md` 与 `doc.md` 保留官方参考资料快照；本 README 描述当前服务。真实 OAuth 登录及真实 LDC 收款仍需使用自己的应用和商户凭据做线上联调。

## 行为回归测试

运行测试命令：

```bash
python3 -m unittest discover -s tests
```
