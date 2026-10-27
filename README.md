# Kegel - 每日提肛打卡

基于 LINUX DO Connect 身份认证的每日提肛打卡站点。使用 Python 3.14 及以上版本的标准库与 SQLite，无需安装第三方依赖。整体采用现代简约设计（纯净白底、深色字体与青绿点缀，告别沉重边框与背景图片），提供沉浸平滑的淡入淡出练习体验。

站点结构：
- **首页 `/`**：初始仅居中展示一行「你今天提肛了吗？」。每组练习均需点击触发并带有倒计时，倒计时结束后平滑淡出淡入至下一组提示；三组完成后展示今日名次卡片、领取按钮、今日榜单、奖励规则与额度进度条。
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

配置完整的 `LINUXDO_CLIENT_ID` 与 `LINUXDO_CLIENT_SECRET` 后，未登录访客访问首页、商店、赞助页或管理页会直接进入 LINUX DO 授权登录，不会先进行匿名打卡；相关用户数据和练习接口会返回 `401`。登录成功后回到原页面，仍需按原规则完成打卡才能领取奖励。登录 Cookie 有效期为 **5 天**，有效期内访问已认证页面或业务接口时自动续至访问后的 5 天；连续 5 天未访问或主动退出后需重新登录。图标、支付通知与使用独立口令的管理/触发接口保持原访问方式。

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

日期和每日截止时间均按 `Asia/Shanghai` 计算。当天在开放后才能开始签到；默认每日 `22:00` 到点开放，也可由管理员手动提前开放或由外部条件触发。用户完成三个步骤，每步默认至少间隔 8 秒。名次在最后一步完成时分配，同一 OAuth 用户每天只能获得一个名次；站内积分奖励随完成时的名次固定。默认第 1–10 名各 `1000` 站内积分，第 11–20 名各 `500`，第 21–50 名各 `100`；奖励区间可配置，金额为整数。用户完成后主动领取，同一天的同一奖励只入账一次。

每次点击触发一组都会请求服务端：第一组 `POST /api/session/start`，第二、三组 `POST /api/session/step`；服务端持久化组次、账号或匿名访客、本轮标识、最短间隔和触发时间。第三组计时结束调用 `POST /api/session/complete`。完成和领取时均核对三组记录及服务端时间间隔，修改浏览器倒计时不能提前领取。后台可查看最近 200 次有效触发，过早或无效的触发请求也保留在访问频率记录中。

从每次触发开始计算，**达到十分钟仍未进入下一组，本轮失效并回到第一组**；下一次点击创建新的一轮，旧触发记录保留。每次有效进入下一组会重新计算十分钟，刷新页面可恢复尚未失效的进度。没有新规则所需完整触发记录的旧进行中练习需要重新开始。

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
  - **品类与配置**：商品品类固定为 `LDC`。后台新建或编辑商品时，选择品类、输入积分售价、发货 LDC 数量、单人每日限购数及全站每日总限购数（0 为不限）。
  - **购买自动发货**：用户点击「立即兑换」确认后，系统在写事务内扣减站内积分并调用 Linux DO Credit 官方商户接口 (`POST /lpay/distribute`) 自动转账至用户的 Linux DO 账户。发货成功更新订单流水；发货失败自动全额退还扣减的积分；网络超时记录待核对状态。未配置商户凭据时安全运行于模拟发货模式。
  - **每日兑换额度**：商品按 `ldc_amount` 精确金额占用全站额度；处理中、成功、模拟和待核对订单占额，失败订单释放额度。额度按北京时间每日重置，设为 `0` 仅停止兑换。
- **独立赞助 (`/donate`)**：支持使用 LINUX DO Connect 登录身份发起 LDC 赞助订单，填写金额后跳转官方 LDC 支付平台。赞助**不会增加站内积分**。生产环境配置 `LDC_DONATION_ENABLED=true`、商户 `LDC_CLIENT_ID` / `LDC_CLIENT_SECRET` 和公网 HTTPS `APP_BASE_URL`。异步通知地址为 `<APP_BASE_URL>/payments/ldc/notify`。
- **赞助榜**：页面公开展示已确认到账的 LDC 赞助榜（按累计赞助金额排序，显示排名、用户名、总额及次数），登录用户可查看自己的赞助订单。只有服务端通过 MD5 验签及订单对账后才会计入榜单，重复通知不会重复累计，浏览器跳转回页面不会确认到账。
## 部署边界

SQLite 部署仅支持单主机、单应用进程。不要让多个进程或多台主机同时运行并共享该数据库；单应用进程负责调度。生产应使用 HTTPS 反向代理，配置至少 32 字符的随机 `APP_SECRET`、独立管理与触发口令，并保护数据库及备份中的身份、访问和交易记录。迁移旧项目时默认新建 `checkin.db`，不读取或转换旧红包数据库。若现有签到数据库包含旧版支付记录，迁移仅保留历史审计，不将已支付的 LDC 转成站内积分。

`api.md` 与 `doc.md` 保留官方参考资料快照；本 README 描述当前服务。真实 OAuth 登录及真实 LDC 收款仍需使用自己的应用和商户凭据做线上联调。

## 行为回归测试

运行测试命令：

```bash
python3 -m unittest discover -s tests
```
